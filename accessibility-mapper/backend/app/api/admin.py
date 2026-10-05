"""Administrator endpoints: analytics, tickets, resolution, seeding.

Every route here sits behind ``AdminGuard``, which accepts an ``X-Admin-Token``
header matching ``ADMIN_TOKEN`` or, outside production, an admin JWT.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.deps import AdminGuard, DbSession
from app.core.constants import CATEGORY_TTL_HOURS
from app.db.models import Barrier, BarrierEvent, MaintenanceTicket, utcnow
from app.schemas.admin import (
    ActionOut,
    AnalyticsOut,
    ResolveRequest,
    SweepOut,
    TicketOut,
    TicketStatusRequest,
)
from app.services import barrier_service
from app.services.graph_service import graph_service
from app.services.ticket_service import (
    PRIORITY_ORDER,
    open_ticket_for_barrier,
    set_ticket_status,
)

logger = logging.getLogger("abm.api.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get(
    "/analytics",
    response_model=AnalyticsOut,
    summary="Heatmap dataset, recurring-barrier breakdown, resolution KPIs, tickets",
)
def analytics(db: DbSession, _user: AdminGuard) -> AnalyticsOut:
    return AnalyticsOut.model_validate(barrier_service.analytics(db))


@router.get("/tickets", summary="Maintenance ticket queue (priority ordered)")
def tickets(
    db: DbSession,
    _user: AdminGuard,
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
) -> dict:
    stmt = select(MaintenanceTicket)
    if status_filter:
        stmt = stmt.where(MaintenanceTicket.status == status_filter)
    if priority:
        stmt = stmt.where(MaintenanceTicket.priority == priority)
    rows = list(db.scalars(stmt))
    rows.sort(
        key=lambda t: (
            PRIORITY_ORDER.get(t.priority, 9),
            -(t.impact_score or 0.0),
            t.created_at,
        )
    )
    items = [TicketOut.model_validate(ticket.to_dict()).model_dump() for ticket in rows]
    return {
        "total": len(items),
        "open": sum(1 for t in rows if t.status != "resolved"),
        "items": items,
    }


@router.patch(
    "/tickets/{ticket_id}",
    response_model=TicketOut,
    summary="Move a ticket between open / in_progress / resolved",
)
def patch_ticket(
    ticket_id: int, payload: TicketStatusRequest, db: DbSession, user: AdminGuard
) -> TicketOut:
    ticket = db.get(MaintenanceTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Ticket {ticket_id} not found")
    actor = user.email if user else "operations-desk"
    set_ticket_status(db, ticket, payload.status, actor=actor)
    if payload.assigned_team:
        ticket.assigned_team = payload.assigned_team
    if payload.note:
        ticket.detail = f"{ticket.detail}\n[{actor}] {payload.note}" if ticket.detail else f"[{actor}] {payload.note}"

    barrier = db.get(Barrier, ticket.barrier_id) if ticket.barrier_id else None
    if barrier is not None:
        graph_service.sync_barrier_penalties(db, [barrier.edge_id])
    db.commit()
    db.refresh(ticket)
    return TicketOut.model_validate(ticket.to_dict())


@router.patch(
    "/barriers/{barrier_id}/resolve",
    response_model=ActionOut,
    summary="Resolve a barrier - clears the dynamic weight penalty immediately",
)
def resolve_barrier(
    barrier_id: int, payload: ResolveRequest, db: DbSession, user: AdminGuard
) -> ActionOut:
    actor = payload.actor or (user.email if user else "facilities-dashboard")
    try:
        result = barrier_service.resolve_barrier(
            db,
            barrier_id,
            actor=actor,
            resolution_note=payload.resolution_note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionOut.model_validate(result)


@router.post(
    "/barriers/{barrier_id}/reopen",
    response_model=ActionOut,
    summary="Re-assert a barrier that came back after being 'fixed'",
)
def reopen_barrier(
    barrier_id: int,
    payload: ResolveRequest,
    db: DbSession,
    user: AdminGuard,
) -> ActionOut:
    actor = payload.actor or (user.email if user else "facilities-dashboard")
    try:
        result = barrier_service.reopen_barrier(
            db, barrier_id, actor=actor, reason=payload.resolution_note
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ActionOut.model_validate(result)


@router.post(
    "/barriers/{barrier_id}/verify",
    response_model=ActionOut,
    summary="Manual verification by campus staff",
)
def verify_barrier(
    barrier_id: int,
    db: DbSession,
    user: AdminGuard,
    note: str | None = Query(default=None, max_length=300),
) -> ActionOut:
    barrier = db.get(Barrier, barrier_id)
    if barrier is None:
        raise HTTPException(status_code=404, detail=f"Barrier {barrier_id} not found")
    actor = user.email if user else "facilities-dashboard"
    barrier.status = "verified"
    barrier.verified_at = utcnow()
    barrier.updated_at = utcnow()
    db.add(
        BarrierEvent(
            barrier_id=barrier.id,
            event_type="verified_manually",
            actor=actor,
            detail=note or "Verified by campus staff from the dashboard.",
        )
    )
    ticket = open_ticket_for_barrier(db, barrier, actor=actor)
    barrier.ticket_id = ticket.id
    sync = graph_service.sync_barrier_penalties(db, [barrier.edge_id])
    db.commit()
    db.refresh(barrier)
    return ActionOut(
        action="verified",
        message=f"{barrier.label} verified and queued for {ticket.assigned_team}.",
        barrier=barrier.to_dict(),
        ticket=ticket.to_dict(),
        graph=sync,
    )


@router.post(
    "/maintenance/sweep",
    response_model=SweepOut,
    summary="Expire stale unconfirmed reports and recompute graph weights",
)
def sweep(db: DbSession, _user: AdminGuard) -> SweepOut:
    expired = barrier_service.expire_stale_barriers(db)
    graph_service.recompute_weights(db)
    db.commit()
    return SweepOut(
        expired=expired,
        message=(
            f"{expired} stale report(s) expired; edge weights recomputed."
            if expired
            else "Nothing to expire. Edge weights recomputed."
        ),
    )


@router.get("/policies", summary="Published thresholds the dashboard enforces")
def policies(_user: AdminGuard) -> dict:
    from app.core.config import settings

    return {
        "auto_verify_confidence": settings.barrier_confidence_threshold,
        "consensus_confirmations": settings.confirmation_threshold,
        "duplicate_radius_m": settings.duplicate_radius_m,
        "barrier_weight_multiplier": settings.barrier_weight_multiplier,
        "default_ttl_hours": settings.barrier_ttl_hours,
        "ttl_by_category": CATEGORY_TTL_HOURS,
        "public_report_auto_verify": settings.public_report_auto_verify,
        "max_reports_per_hour": settings.max_reports_per_hour,
        "max_reports_per_day": settings.max_reports_per_day,
        "max_upload_mb": round(settings.max_upload_bytes / 1e6, 1),
        "redaction": {
            "faces": settings.blur_faces,
            "license_plates": settings.blur_license_plates,
            "min_area_px": settings.redaction_min_area_px,
        },
        "walk_speed_mps": {
            "walk": settings.walk_speed_mps,
            "wheelchair": settings.wheelchair_speed_mps,
        },
        "ghost_space": {
            "grace_minutes": settings.ghost_grace_minutes,
            "probability_threshold": settings.ghost_probability_threshold,
            "reclaim_window_minutes": settings.ghost_reclaim_window_minutes,
            "beta_alpha": settings.ghost_beta_alpha,
            "beta_beta": settings.ghost_beta_beta,
            "energy_is_estimate": True,
            "occupancy_is_simulated": True,
        },
        "auth": {
            "admin_token_required_in_production": settings.admin_token != "",
            "mechanism": "X-Admin-Token header, or an admin JWT locally",
        },
    }


@router.post(
    "/seed",
    summary="Idempotently create + seed the database",
    description=(
        "Safe to call repeatedly: creates tables if missing and only seeds when "
        "the campus graph is empty. This is how a fresh deployment is populated "
        "(`curl -X POST .../admin/seed -H 'X-Admin-Token: ...'`)."
    ),
)
def admin_seed(db: DbSession, _user: AdminGuard) -> dict:
    from app.core.database import Base, engine
    from app.db import models as _models  # noqa: F401
    from app.db import space_models as _space_models  # noqa: F401
    from app.db.seed import seed_if_empty

    Base.metadata.create_all(bind=engine)
    created = seed_if_empty(db)
    graph_service.invalidate()
    graph_service.ensure_fresh(db)
    db.commit()
    return {
        "status": "seeded" if created else "already_present",
        "created": created,
        "message": (
            "Campus + Ghost Space demo data created."
            if created
            else "Database already had data - left untouched (idempotent)."
        ),
    }


@router.post(
    "/demo/reset",
    summary="Re-arm the demo: wipe and re-seed campus + Ghost Space",
    description=(
        "Restores the scripted state: blocked More Hall ramp, broken Health "
        "Sciences lift, 19 rooms, ~46 bookings of which ~30% are ghosts, and a "
        "live clock reset to real time. Requires the admin token."
    ),
)
def admin_demo_reset(db: DbSession, _user: AdminGuard) -> dict:
    from app.db.seed import seed
    from app.services.media_service import reset_quotas, write_clock

    counts = seed(db, reset=True)
    quotas = reset_quotas(db)
    write_clock(
        db,
        {
            "mode": "live",
            "speed": 1.0,
            "base": utcnow().isoformat(),
            "offset_seconds": 0.0,
            "playing": True,
        },
    )
    graph_service.invalidate()
    graph_service.recompute_weights(db)
    db.commit()
    logger.info("demo state reset: %s (%s quota rows cleared)", counts, quotas)
    return {
        "status": "reset",
        "counts": counts,
        "quotas_cleared": quotas,
        "message": "Demo data restored to its scripted state.",
    }
