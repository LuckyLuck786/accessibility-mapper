"""Test fixtures.

The database URL is redirected to a throwaway SQLite file *before* the app is
imported, because ``Settings`` is cached at import time. Each session gets a
freshly seeded campus + Ghost Space day so assertions on the scripted demo
state are stable.

Tests run in demo-clock mode by default: the Ghost Space engine reads its "now"
from ``app_state``, and a wall-clock now would make every release-rule assertion
flaky.
"""

from __future__ import annotations

import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="abm-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["AUTO_SEED"] = "true"
os.environ["ENVIRONMENT"] = "test"
os.environ["BLUR_FACES"] = "true"
os.environ["BLUR_LICENSE_PLATES"] = "true"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
# Public reports must not auto-verify; that is the deployment policy we assert.
os.environ["PUBLIC_REPORT_AUTO_VERIFY"] = "false"
# The functional suite posts far more photos than a real client would, and every
# TestClient shares one IP so they all share a quota bucket. The limit itself is
# asserted on purpose in ``tests/test_abuse_limits.py`` with its own settings.
os.environ["MAX_REPORTS_PER_HOUR"] = "500"
os.environ["MAX_REPORTS_PER_DAY"] = "5000"

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.graph_service import graph_service  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _database() -> None:
    init_db(seed=True)
    with SessionLocal() as db:
        graph_service.invalidate()
        graph_service.recompute_weights(db)
        db.commit()


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db_session():
    """A session with Ghost Space re-seeded and the clock reset.

    The seed itself is session-scoped (seeding 19 rooms and ~49 bookings per
    test would dominate the runtime), but the Ghost Space *day* is mutable state
    - releases, check-ins, clock jumps - so each test gets it back at the
    scripted starting point. Tests that assert on a fresh world must be able to
    trust that.
    """
    from app.db.seed import _seed_spaces, seed
    from app.db.space_models import Booking, NoShowStat, OccupancySignal, Room
    from app.db.models import CampusNode
    from app.services import space_service

    session = SessionLocal()
    try:
        nodes = {n.id: n for n in session.query(CampusNode).all()}
        seed(session, reset=True)
        session.expire_all()
        graph_service.invalidate()
        # Pin the clock to the busiest part of the seeded teaching day (17:00 on
        # the demo day: four bookings in flight, two of them ghosts already past
        # the grace period) so the release rule has something to act on.
        anchor = space_service._demo_anchor() + timedelta(hours=8)
        space_service.set_clock(session, mode="demo", jump_to=anchor, speed=1.0)
        session.commit()
        yield session
    finally:
        session.close()


@pytest.fixture
def admin_headers() -> dict[str, str]:
    """The deployment's real admin gate: the X-Admin-Token header."""
    from app.core.config import settings

    return {"X-Admin-Token": settings.admin_token}


@pytest.fixture(scope="session")
def admin_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@campus.edu", "password": "admin123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="session")
def staff_token(client: TestClient) -> str:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "facilities@campus.edu", "password": "facilities123"},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


# --- demo coordinates reused across the suite ------------------------------
RED_SQUARE = (47.65599, -122.30836)
MORE_HALL = (47.65622, -122.30424)
HUB = (47.65518, -122.30498)
HSB_CLINIC_L3 = (47.65031, -122.30936)