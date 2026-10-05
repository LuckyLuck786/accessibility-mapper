"""SQLAlchemy engine / session wiring for both local SQLite and serverless Postgres.

Serverless constraints this module exists to satisfy
---------------------------------------------------
* **No connection pooling.** Vercel recycles function instances aggressively, so
  a warm pool is mostly dead sockets against Neon's idle-connection reaper. We
  use ``NullPool`` and pay the handshake cost on every cold-ish request, which
  is cheaper than the ``SLEEPER has been terminated`` 500s a pool produces.
* **No PostGIS.** Columns are plain ``Float`` latitude/longitude and every
  proximity query is haversine in Python (see :mod:`app.core.geo`). That keeps
  the dependency list short and the bundle small. If someone *does* enable
  ``USE_POSTGIS`` the optional DDL below adds GiST indexes on top.
* **No filesystem writes.** Media bytes live in the ``media_objects`` table and
  are streamed back out by ``GET /api/v1/media/{id}``.
* **Bounded retries.** Neon drops connections on idle timeout; retry the
  initial connect a couple of times rather than 500-ing the user's first
  request after a quiet period.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.core.config import settings

logger = logging.getLogger("abm.db")


class UTCDateTime(TypeDecorator):
    """A timezone-aware UTC timestamp that behaves identically on SQLite and Postgres.

    Why this exists: SQLite has no native ``timestamptz`` and silently drops the
    offset on round-trip, so a value written as ``2026-10-05T09:00:00+00:00``
    comes back naive. Comparing that to an aware ``now()`` raises
    ``TypeError: can't compare offset-naive and offset-aware datetimes``. Rather
    than sprinkle ``_aware()`` through every query - and get it wrong once - we
    normalise at the type boundary: every value in and out is tz-aware UTC.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


def _build_engine() -> Engine:
    url = settings.resolved_database_url
    kwargs: dict = {"future": True, "pool_pre_ping": True}

    if settings.is_sqlite:
        # check_same_thread=False: TestClient runs the app in another thread.
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    else:
        from sqlalchemy.pool import NullPool

        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {
            "connect_timeout": 10,
            # Neon's pooler closes sessions held open past this; keep it short.
            "keepalives": 1,
            "keepalives_idle": 20,
            "keepalives_interval": 10,
        }

    engine = create_engine(url, **kwargs)

    if settings.is_sqlite:

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            dbapi_connection.commit()
            cursor.close()

    return engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _wait_for_database(timeout_s: float = 30.0) -> None:
    """Block until the database answers ``SELECT 1`` (cold-start friendly)."""
    deadline = time.monotonic() + timeout_s
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # pragma: no cover - depends on deployment
            if time.monotonic() >= deadline:
                raise
            delay = min(2.0 * attempt, 5.0)
            logger.warning(
                "database not ready (attempt %s: %s) - retrying in %.1fs",
                attempt,
                exc.__class__.__name__,
                delay,
            )
            time.sleep(delay)


#: Optional PostGIS upgrade. Off by default: plain float columns + haversine
#: are enough at campus scale and keep the deployed bundle small.
POSTGIS_DDL = """
CREATE EXTENSION IF NOT EXISTS postgis;
ALTER TABLE nodes   ADD COLUMN IF NOT EXISTS geom geography(Point, 4326);
ALTER TABLE edges   ADD COLUMN IF NOT EXISTS geom geography(LineString, 4326);
ALTER TABLE barriers ADD COLUMN IF NOT EXISTS geom geography(Point, 4326);
UPDATE nodes   SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography WHERE geom IS NULL;
UPDATE barriers SET geom = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)::geography WHERE geom IS NULL;
CREATE INDEX IF NOT EXISTS idx_nodes_geom   ON nodes   USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_edges_geom   ON edges   USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_barriers_geom ON barriers USING GIST (geom);
"""


def init_db(*, seed: bool = True) -> None:
    """Create tables, optionally enable PostGIS, optionally seed. Idempotent."""
    from app.db import models  # noqa: F401  (register mappers)
    from app.db import space_models  # noqa: F401

    _wait_for_database()
    Base.metadata.create_all(bind=engine)

    if settings.use_postgis and not settings.is_sqlite:  # pragma: no cover
        try:
            with engine.begin() as conn:
                conn.execute(text(POSTGIS_DDL))
            logger.info("PostGIS spatial columns + GiST indexes ready")
        except Exception as exc:
            logger.warning("PostGIS upgrade skipped (%s); using haversine path", exc)

    if seed and settings.auto_seed:
        from app.db.seed import seed_if_empty

        with SessionLocal() as db:
            seed_if_empty(db)


def database_kind() -> str:
    if settings.use_postgis and not settings.is_sqlite:
        return "postgresql+postgis"
    if settings.is_sqlite:
        return "sqlite"
    return "postgresql"


# -----------------------------------------------------------------------
# graph_version: the stateless-instance handshake
# -----------------------------------------------------------------------
# Function instances cannot trust in-memory graph state across requests. Every
# mutation bumps a single row; every request compares the cached value and
# rebuilds the NetworkX graph only when it moved. One indexed primary-key
# SELECT per request is far cheaper than rebuilding the graph per request.
GRAPH_VERSION_KEY = "graph_version"


def read_graph_version(db: Session) -> int:
    """Current graph version, creating the row on first use."""
    from app.db.models import AppState

    row = db.get(AppState, GRAPH_VERSION_KEY)
    if row is None:
        row = AppState(key=GRAPH_VERSION_KEY, value="1", updated_at=_now())
        db.add(row)
        db.flush()
        return 1
    try:
        return int(row.value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return 1


def bump_graph_version(db: Session) -> int:
    """Invalidate every warm instance's cached graph. Returns the new version."""
    from app.db.models import AppState

    row = db.get(AppState, GRAPH_VERSION_KEY)
    if row is None:
        row = AppState(key=GRAPH_VERSION_KEY, value="2", updated_at=_now())
        db.add(row)
        db.flush()
        return 2
    try:
        current = int(row.value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        current = 1
    row.value = str(current + 1)
    row.updated_at = datetime.now(UTC)
    db.flush()
    return current + 1


def _now() -> datetime:
    return datetime.now(UTC)


def get_state(db: Session, key: str, default: str | None = None) -> str | None:
    from app.db.models import AppState

    row = db.get(AppState, key)
    return row.value if row is not None else default


def set_state(db: Session, key: str, value: str) -> None:
    from app.db.models import AppState

    row = db.get(AppState, key)
    if row is None:
        db.add(AppState(key=key, value=value))
    else:
        row.value = value
        row.updated_at = _now()


__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "init_db",
    "database_kind",
    "read_graph_version",
    "bump_graph_version",
    "get_state",
    "set_state",
]