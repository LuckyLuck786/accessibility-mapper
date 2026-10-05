"""Health and capability discovery.

Demo reset and seeding are **admin** actions and live in ``app/api/admin.py``,
gated by ``X-Admin-Token``. They are deliberately not reachable from the public
system router.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.config import settings
from app.core.database import database_kind
from app.db.models import Barrier, CampusEdge, CampusNode, MaintenanceTicket, User
from app.schemas.campus import SystemStatusOut
from app.services.cv_service import cv_service
from app.services.graph_service import graph_service

logger = logging.getLogger("abm.api.system")

router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness probe (used by the platform healthcheck)")
def health(db: DbSession) -> dict:
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "database": database_kind(),
        "nodes": db.scalar(select(CampusNode.id).limit(1)) is not None,
    }


@router.get("/cv/status", summary="Which classifier is active right now")
def cv_status() -> dict:
    return cv_service.status()


@router.get("/system/status", response_model=SystemStatusOut, summary="Full capability report")
def system_status(db: DbSession) -> SystemStatusOut:
    return SystemStatusOut(
        app=settings.app_name,
        version=settings.version,
        environment=settings.environment,
        database=database_kind(),
        graph=graph_service.stats(db),
        cv=cv_service.status(),
        routing={
            "algorithm": "A* over a NetworkX MultiDiGraph",
            "weight_formula": "distance_m * step_free_penalty * (1 + multiplier * active_barriers)",
            "barrier_multiplier": settings.barrier_weight_multiplier,
            "max_snap_distance_m": settings.max_snap_distance_m,
            "alert_radius_m": 60.0,
            "graph_version": graph_service.graph_version,
            "stateless": "graph rebuilt from the DB whenever graph_version moves",
        },
        policies={
            "auto_verify_confidence": settings.barrier_confidence_threshold,
            "consensus_confirmations": settings.confirmation_threshold,
            "duplicate_radius_m": settings.duplicate_radius_m,
            "ttl_hours": settings.barrier_ttl_hours,
            "public_report_auto_verify": settings.public_report_auto_verify,
            "max_reports_per_hour": settings.max_reports_per_hour,
            "max_upload_mb": round(settings.max_upload_bytes / 1e6, 1),
            "redaction": {
                "faces": settings.blur_faces,
                "license_plates": settings.blur_license_plates,
            },
        },
        ghost_space={
            "grace_minutes": settings.ghost_grace_minutes,
            "probability_threshold": settings.ghost_probability_threshold,
            "reclaim_window_minutes": settings.ghost_reclaim_window_minutes,
            "method": (
                "Beta-smoothed historical no-show rate per (organizer_type, "
                "weekday, hour) combined with live zero-headcount evidence. "
                "A smoothed historical rate, not a trained model."
            ),
            "energy_is_estimate": True,
        },
    )


@router.get("/system/dataset", summary="Row counts for every table")
def dataset(db: DbSession) -> dict:
    from app.db.space_models import Booking, NoShowStat, OccupancySignal, Room, SpaceRequest

    return {
        "nodes": len(list(db.scalars(select(CampusNode.id)))),
        "edges": len(list(db.scalars(select(CampusEdge.id)))),
        "barriers": len(list(db.scalars(select(Barrier.id)))),
        "tickets": len(list(db.scalars(select(MaintenanceTicket.id)))),
        "users": len(list(db.scalars(select(User.id)))),
        "active_barriers": len(
            list(
                db.scalars(
                    select(Barrier.id).where(
                        Barrier.status.in_(("unverified", "verified", "in_progress"))
                    )
                )
            )
        ),
        "rooms": len(list(db.scalars(select(Room.id)))),
        "bookings": len(list(db.scalars(select(Booking.id)))),
        "occupancy_signals": len(list(db.scalars(select(OccupancySignal.id)))),
        "space_requests": len(list(db.scalars(select(SpaceRequest.id)))),
        "noshow_stats": len(list(db.scalars(select(NoShowStat.id)))),
        "ghost_released": len(
            list(db.scalars(select(Booking.id).where(Booking.status == "ghost_released")))
        ),
    }
