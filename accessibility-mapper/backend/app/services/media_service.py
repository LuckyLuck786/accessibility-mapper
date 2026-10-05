"""Media delivery from Postgres ``bytea`` + DB-backed abuse limits.

Two small services that exist purely because the app runs on a read-only
filesystem with no Redis:

``store_analysis`` / ``fetch_media``
    Redacted JPEGs live in the ``media_objects`` table. Nothing is ever written
    to disk, and ``GET /api/v1/media/{id}`` streams the bytes straight back.

``report_quota``
    Counts reports per client per hour/day in the ``report_counters`` table. The
    client key is a salted hash of the IP (or the signed-in e-mail), so the
    limiter works without storing an address or requiring an account.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_state, set_state
from app.db.models import Barrier, MediaObject, ReportCounter

logger = logging.getLogger("abm.media")


# -----------------------------------------------------------------------
# Media
# -----------------------------------------------------------------------
def client_key(request_ip: str | None, reporter_label: str | None) -> str:
    """Stable, privacy-preserving identity for quota counting."""
    if reporter_label and not reporter_label.startswith("anon-"):
        digest = hashlib.sha256(f"{settings.jwt_secret}:user:{reporter_label}".encode())
        return f"user-{digest.hexdigest()[:24]}"
    raw = request_ip or "unknown"
    digest = hashlib.sha256(f"{settings.jwt_secret}:ip:{raw}".encode())
    return f"ip-{digest.hexdigest()[:24]}"


def store_analysis(db: Session, analysis) -> dict[str, Any]:
    """Persist one :class:`AnalysisResult` and return its URLs.

    The write itself lives on :class:`~app.services.cv_service.CVService`
    because it needs the redaction encoder that produced ``analysis``.
    """
    from app.services.cv_service import cv_service

    return cv_service.store(db, analysis)


def attach_to_barrier(db: Session, barrier: Barrier, stored: dict[str, Any]) -> None:
    barrier.image_path = stored.get("media_id")
    barrier.thumbnail_path = stored.get("thumbnail_id") or stored.get("media_id")


def fetch_media(db: Session, media_id: str, *, variant: str = "full") -> MediaObject | None:
    media = db.get(MediaObject, media_id)
    if media is None:
        return None
    return media


# -----------------------------------------------------------------------
# Abuse limits
# -----------------------------------------------------------------------
def _floor_hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def _floor_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def report_quota(db: Session, key: str, *, now: datetime | None = None) -> dict[str, Any]:
    """Return the client's quota state and whether the report may proceed.

    Raises nothing: the caller decides how to reject (HTTP 429).
    """
    now = now or datetime.now(UTC)
    hour_start = _floor_hour(now)
    day_start = _floor_day(now)

    hourly = _bump(db, key, "hour", hour_start)
    daily = _bump(db, key, "day", day_start)

    allowed = (
        hourly.count <= settings.max_reports_per_hour
        and daily.count <= settings.max_reports_per_day
    )
    return {
        "allowed": allowed,
        "client_key": key,
        "hour": {
            "count": hourly.count,
            "limit": settings.max_reports_per_hour,
            "window_start": hourly.window_start.isoformat(),
        },
        "day": {
            "count": daily.count,
            "limit": settings.max_reports_per_day,
            "window_start": daily.window_start.isoformat(),
        },
        "reason": (
            None
            if allowed
            else (
                f"Hourly public-report limit reached "
                f"({settings.max_reports_per_hour}/hour). Try again later."
                if hourly.count > settings.max_reports_per_hour
                else f"Daily public-report limit reached "
                f"({settings.max_reports_per_day}/day)."
            )
        ),
    }


def _bump(db: Session, key: str, kind: str, window_start: datetime) -> ReportCounter:
    row = db.scalar(
        select(ReportCounter).where(
            ReportCounter.client_key == key,
            ReportCounter.window_kind == kind,
            ReportCounter.window_start == window_start,
        )
    )
    if row is None:
        row = ReportCounter(
            client_key=key, window_kind=kind, window_start=window_start, count=1
        )
        db.add(row)
    else:
        row.count += 1
    db.flush()
    return row


def reset_quotas(db: Session) -> int:
    """Clear every counter (part of ``POST /api/v1/admin/demo/reset``)."""
    rows = list(db.scalars(select(ReportCounter)))
    for row in rows:
        db.delete(row)
    db.flush()
    return len(rows)


# -----------------------------------------------------------------------
# Demo clock (shared by the app state store)
# -----------------------------------------------------------------------
CLOCK_KEY = "demo_clock"


def read_clock(db: Session) -> dict[str, Any]:
    """Current demo-clock state. Everything time-based reads this, not ``utcnow()``."""
    import json

    raw = get_state(db, CLOCK_KEY)
    if not raw:
        return {
            "mode": "live",
            "speed": 1.0,
            "base": datetime.now(UTC).isoformat(),
            "offset_seconds": 0.0,
            "playing": True,
        }
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return {
            "mode": "live",
            "speed": 1.0,
            "base": datetime.now(UTC).isoformat(),
            "offset_seconds": 0.0,
            "playing": True,
        }
    return payload


def write_clock(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    import json

    set_state(db, CLOCK_KEY, json.dumps(payload))
    return payload


def clock_now(db: Session) -> datetime:
    """The demo 'now' - the single clock the whole app reasons about."""
    state = read_clock(db)
    if state.get("mode") != "demo":
        return datetime.now(UTC)
    base = datetime.fromisoformat(state["base"])
    if base.tzinfo is None:
        base = base.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - base).total_seconds() * float(state.get("speed", 1.0))
    return base + timedelta(seconds=float(state.get("offset_seconds", 0.0)) + elapsed)


__all__ = [
    "attach_to_barrier",
    "client_key",
    "clock_now",
    "fetch_media",
    "read_clock",
    "report_quota",
    "reset_quotas",
    "store_analysis",
    "write_clock",
]