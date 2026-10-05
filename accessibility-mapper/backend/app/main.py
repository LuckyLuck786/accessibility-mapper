"""Ghost Space + Accessibility Mapper - FastAPI application (serverless-ready).

Boot sequence
-------------
1. Create tables (idempotent). On a cold serverless start this is a handful of
   ``CREATE TABLE IF NOT EXISTS`` statements against hosted Postgres.
2. Seed only when the database is genuinely empty - never on every cold start.
3. Expire anything stale so the map is honest on first paint.
4. Serve the API at ``/api/v1``, redacted media at ``/api/v1/media/{id}``.

Serverless notes
----------------
* **No filesystem writes.** Redacted photos live in Postgres as ``bytea`` and
  are streamed back from ``/api/v1/media/{id}``. There is no media directory,
  because a Vercel function's filesystem is read-only outside ``/tmp``.
* **No background work.** Everything that used to be a ``BackgroundTask`` now
  runs inside the request; a frozen function would never run it anyway.
* **Stateless instances.** The NetworkX graph is rebuilt from the DB and keyed
  by the shared ``graph_version`` row, so a warm instance picks up barrier
  changes made by another instance without shared memory.
* **Same-origin.** The frontend is served by the same Vercel project and calls
  ``/api/v1`` relatively, so no CORS configuration is needed in production.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from app.api import admin, auth, barriers, demo, routes, spaces, system
from app.core.config import settings
from app.core.database import SessionLocal, database_kind, init_db
from app.services import barrier_service
from app.services.cv_service import cv_service
from app.services.graph_service import graph_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s :: %(message)s",
)
logger = logging.getLogger("abm")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("starting %s v%s (%s)", settings.app_name, settings.version, settings.environment)
    try:
        init_db(seed=True)
        with SessionLocal() as db:
            graph_service.invalidate()
            graph_service.ensure_fresh(db)
            graph_service.recompute_weights(db)
            expired = barrier_service.expire_stale_barriers(db)
            db.commit()
            stats = graph_service.stats(db)
        logger.info(
            "campus graph ready: %s nodes / %s edges (v%s)",
            stats["nodes"],
            stats["edges"],
            stats.get("graph_version"),
        )
        if expired:
            logger.info("expired %s stale barrier(s) during startup", expired)
        logger.info("classifier: %s", cv_service.engine_name)
    except Exception:
        # A database hiccup must not stop the function from booting - /health
        # should still answer so the platform's probe is satisfied and the real
        # error surfaces on the first request that touches the data.
        logger.exception("startup initialisation failed; serving /health only")

    yield
    logger.info("shutting down")


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "Campus space and campus accessibility are one problem. Ghost Space "
        "finds booked-but-empty rooms and releases them; the Barrier Mapper "
        "knows which routes are blocked today. Together a student who needs a "
        "step-free room gets only rooms that are actually free AND actually "
        "reachable right now."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "system", "description": "Health, capability discovery, dataset counts"},
        {"name": "demo", "description": "Demo clock controlling 'now' for the whole app"},
        {"name": "auth", "description": "Demo JWT auth for the facilities dashboard"},
        {"name": "barriers", "description": "Citizen reporting, privacy pipeline, GeoJSON feed"},
        {"name": "routing", "description": "Step-free A* routing over the campus graph"},
        {"name": "spaces", "description": "Ghost Space: rooms, bookings, matching, metrics"},
        {"name": "admin", "description": "Analytics, tickets, Ghost Space overrides, seeding"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time-Ms", "X-Graph-Version"],
)

PREFIX = settings.api_prefix
app.include_router(system.router, prefix=PREFIX)
app.include_router(demo.router, prefix=PREFIX)
app.include_router(auth.router, prefix=PREFIX)
app.include_router(barriers.router, prefix=PREFIX)
app.include_router(barriers.media_router, prefix=PREFIX)
app.include_router(routes.router, prefix=PREFIX)
app.include_router(spaces.router, prefix=PREFIX)
app.include_router(spaces.admin_router, prefix=PREFIX)
app.include_router(admin.router, prefix=PREFIX)


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
    if elapsed_ms > 1500:
        logger.warning("slow %s %s -> %.0f ms", request.method, request.url.path, elapsed_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "path": request.url.path,
            "type": exc.__class__.__name__,
        },
    )


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/docs")


@app.get(f"{PREFIX}/overview", tags=["system"], summary="One-shot payload for the web client")
def overview() -> dict[str, Any]:
    """Everything the frontend needs to boot without extra round-trips."""
    from app.db.seed import campus_bounds, preset_destinations

    with SessionLocal() as db:
        graph_service.ensure_fresh(db)
        stats = graph_service.stats(db)
        presets = preset_destinations(db)
        bounds = campus_bounds(db)
    return {
        "app": settings.app_name,
        "version": settings.version,
        "database": database_kind(),
        "graph": stats,
        "cv": cv_service.status(),
        "presets": presets,
        "bounds": bounds,
        "formula": "weight = distance_m * step_free_penalty * (1 + 10 * active_barriers)",
        "policies": {
            "auto_verify_confidence": settings.barrier_confidence_threshold,
            "consensus_confirmations": settings.confirmation_threshold,
            "duplicate_radius_m": settings.duplicate_radius_m,
            "public_report_auto_verify": settings.public_report_auto_verify,
            "max_upload_mb": round(settings.max_upload_bytes / 1e6, 1),
            "reports_per_hour": settings.max_reports_per_hour,
        },
        "ghost_space": {
            "grace_minutes": settings.ghost_grace_minutes,
            "probability_threshold": settings.ghost_probability_threshold,
            "reclaim_window_minutes": settings.ghost_reclaim_window_minutes,
            "energy_is_estimate": True,
        },
    }