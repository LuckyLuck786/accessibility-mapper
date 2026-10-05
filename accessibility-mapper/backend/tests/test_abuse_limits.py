"""Phase 0 acceptance tests for the public abuse limits.

The rest of the suite raises these limits (see ``conftest``) because every
``TestClient`` shares one IP and therefore one quota bucket. These tests pin the
real deployment behaviour instead, on a dedicated client IP so they never collide
with the functional suite's counters.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

import anyio
import httpx

from app.core.config import settings
from app.main import app

from .test_api import _as_upload, _photo


class _SyncASGITransport(httpx.BaseTransport):
    """Sync facade over httpx's async-only ASGI transport, pinned to one IP."""

    def __init__(self, ip: str) -> None:
        self._ip = ip

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        async def call() -> httpx.Response:
            transport = httpx.ASGITransport(app=app, client=(self._ip, 51000))
            response = await transport.handle_async_request(request)
            # Buffer the async stream and hand back a plain sync response.
            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=await response.aread(),
                extensions=response.extensions,
            )

        return anyio.run(call)


@contextmanager
def _client_for(ip: str):
    """A client whose ASGI scope reports ``ip`` as its address.

    Quota bucketing keys off ``request.client.host``, and Starlette's default
    ``TestClient`` pins that to one address for the whole session. A transport
    with its own ``client`` gives each test a genuinely separate bucket instead
    of faking one.
    """
    client = httpx.Client(
        transport=_SyncASGITransport(ip), base_url="http://testserver"
    )
    try:
        yield client
    finally:
        client.close()


def test_public_report_quota_is_enforced_per_client(client, monkeypatch):
    monkeypatch.setattr(settings, "max_reports_per_hour", 2)

    with _client_for("198.51.100.10") as scoped:
        codes = []
        for index in range(3):
            response = scoped.post(
                "/api/v1/barriers/report",
                files=_as_upload(_photo("obstacle", seed=900 + index)),
                data={
                    "latitude": str(47.6600 + index * 0.004),
                    "longitude": "-122.3020",
                    "category": "obstacle",
                },
            )
            codes.append(response.status_code)

    assert codes[:2] == [201, 201], "the first reports under the limit must succeed"
    assert codes[2] == 429, "the report past the hourly limit must be refused"


def test_a_throttled_client_does_not_consume_a_neighbour_quota(client, monkeypatch):
    """One noisy client must not be able to lock everyone else out."""
    monkeypatch.setattr(settings, "max_reports_per_hour", 1)

    with _client_for("198.51.100.20") as noisy:
        noisy.post(
            "/api/v1/barriers/report",
            files=_as_upload(_photo("obstacle", seed=940)),
            data={"latitude": "47.6610", "longitude": "-122.3020", "category": "obstacle"},
        )
        blocked = noisy.post(
            "/api/v1/barriers/report",
            files=_as_upload(_photo("obstacle", seed=941)),
            data={"latitude": "47.6614", "longitude": "-122.3020", "category": "obstacle"},
        )

    with _client_for("198.51.100.21") as neighbour:
        allowed = neighbour.post(
            "/api/v1/barriers/report",
            files=_as_upload(_photo("obstacle", seed=942)),
            data={"latitude": "47.6620", "longitude": "-122.3020", "category": "obstacle"},
        )

    assert blocked.status_code == 429
    assert allowed.status_code == 201


def test_an_oversized_upload_is_refused_before_any_processing(client):
    with _client_for("198.51.100.30") as scoped:
        oversized = b"\xff\xd8" + b"\x00" * (settings.max_upload_bytes + 1024)
        response = scoped.post(
            "/api/v1/barriers/report",
            files=_as_upload(oversized, name="big.jpg"),
            data={"latitude": "47.6630", "longitude": "-122.3020", "category": "obstacle"},
        )
    assert response.status_code == 413
    assert "limit" in response.json()["detail"]


def test_admin_routes_refuse_anonymous_callers(client):
    """Phase 0 made every mutating admin route token-gated. Lock that in."""
    assert client.post("/api/v1/admin/seed").status_code == 401
    assert client.post("/api/v1/admin/demo/reset").status_code == 401
    assert client.get("/api/v1/admin/analytics").status_code == 401
    assert client.get("/api/v1/admin/tickets").status_code == 401
    assert client.get("/api/v1/admin/policies").status_code == 401
