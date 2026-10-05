"""Barrier endpoints: citizen reporting, GeoJSON feed, confirmations, timeline.

``POST /report`` is the heart of the prototype. It runs the **whole** pipeline
inside the request - privacy redaction, classification, dedupe, and a
high-resolution refinement pass - because a serverless function is frozen the
moment the response is written, so a FastAPI ``BackgroundTask`` would silently
never execute on Vercel.
"""

from __future__ import annotations

import logging

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    DbSession,
    OptionalUser,
    enforce_report_quota,
    reporter_label,
)
from app.core.config import settings
from app.core.constants import (
    BARRIER_CATEGORIES,
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    CATEGORY_SEVERITY,
    STEP_FREE_BLOCKING,
)
from app.db.models import Barrier, BarrierEvent, CampusEdge, MediaObject, utcnow
from app.schemas.barrier import (
    BarrierConfirmRequest,
    BarrierConfirmResponse,
    BarrierListOut,
    BarrierOut,
    BarrierReportResponse,
    BarrierTimelineOut,
    CategoriesOut,
    CategoryInfo,
)
from app.services import barrier_service
from app.services.cv_service import cv_service
from app.services.graph_service import graph_service
from app.services.ticket_service import open_ticket_for_barrier

logger = logging.getLogger("abm.api.barriers")

router = APIRouter(prefix="/barriers", tags=["barriers"])

#: ``GET /api/v1/media/{id}`` - spec-mandated public path for stored redacted
#: photos. Separate router so the URL is not namespaced under /barriers.
media_router = APIRouter(prefix="/media", tags=["media"])

#: The client compresses to <= 1.5 MB in the browser (canvas resize); the server
#: refuses anything larger so a 12 MB phone photo cannot exceed Vercel's 4.5 MB
#: request-body cap.
MAX_UPLOAD_BYTES = settings.max_upload_bytes

REPORT_DESCRIPTION = """
Submit a barrier photo. The pipeline runs **privacy redaction first** (faces and
licence plates are blurred before anything is stored), then barrier
classification, then spatial de-duplication:

* within **15 m** of an active same-category barrier -> the existing report is
  **confirmed** instead of duplicated;
* `confidence >= 0.85` on a **staff** report -> **auto-verified** and a
  maintenance ticket opens;
* `confirmations >= 2` -> **verified by consensus**.

**Public (anonymous) reports always start `unverified` and expire** - they can
never auto-verify on classifier confidence alone. That is the anti-abuse policy;
the classifier verdict is still recorded and shown.
"""


@router.post(
    "/report",
    response_model=BarrierReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Report a barrier (multipart photo + GPS)",
    description=REPORT_DESCRIPTION,
)
async def report_barrier(
    request: Request,
    db: DbSession,
    user: OptionalUser,
    file: UploadFile = File(..., description="JPEG/PNG photo of the barrier (<= 1.5 MB)"),
    latitude: float = Form(..., ge=-90, le=90),
    longitude: float = Form(..., ge=-180, le=180),
    category: str | None = Form(
        default=None, description="Optional reporter override of the classifier verdict"
    ),
    description: str | None = Form(default=None, max_length=1000),
    force_new: bool = Form(
        default=False, description="Ignore duplicate detection and create a new barrier"
    ),
) -> BarrierReportResponse:
    if category and category not in BARRIER_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown category '{category}'. Valid: {', '.join(BARRIER_CATEGORIES)}",
        )

    label = reporter_label(request, user)
    # Rate limit *before* the CPU-heavy CV pass so one abusive client cannot
    # burn function invocations.
    quota = enforce_report_quota(request, label)

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="The uploaded photo is empty.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Photo is {len(raw) / 1e6:.1f} MB - the limit is "
                f"{MAX_UPLOAD_BYTES / 1e6:.1f} MB (the web client compresses "
                f"images automatically)."
            ),
        )

    is_public = user is None
    try:
        result = barrier_service.submit_report(
            db,
            image_bytes=raw,
            filename=file.filename,
            latitude=latitude,
            longitude=longitude,
            category_hint=category,
            description=description,
            reporter=user,
            reporter_label=label,
            force_new=force_new,
            is_public=is_public,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Refinement used to be a BackgroundTask. It is now synchronous: a
    # serverless instance is frozen once the response is written, so the pass
    # would never run in production.
    if result["action"] == "created":
        _refine_report(db, result["barrier"]["id"], raw, category, description, is_public)

    result["quota"] = quota
    return BarrierReportResponse.model_validate(result)


def _refine_report(
    db: Session,
    barrier_id: int,
    raw: bytes,
    category_hint: str | None,
    description: str | None,
    is_public: bool,
) -> None:
    """High-resolution second pass, run inside the request (Phase 0 fix).

    Never raises: a failed refinement must not lose the report the citizen
    already submitted.
    """
    try:
        barrier = db.get(Barrier, barrier_id)
        if barrier is None or barrier.status != "unverified":
            return
        deep = cv_service.refine(
            raw, note=description, category_hint=category_hint
        )
        db.add(
            BarrierEvent(
                barrier_id=barrier.id,
                event_type="refinement_pass",
                actor="classifier",
                detail=(
                    f"High-resolution pass: {deep.category} at "
                    f"{deep.confidence:.2f} confidence ({deep.engine})."
                ),
            )
        )
        if deep.confidence > barrier.confidence:
            barrier.confidence = round(float(deep.confidence), 3)

        # Public reports never auto-verify, whatever the refinement says.
        may_auto_verify = (not is_public) or settings.public_report_auto_verify
        if (
            may_auto_verify
            and deep.confidence >= settings.barrier_confidence_threshold
            and deep.category == barrier.category
        ):
            barrier.status = "verified"
            barrier.verified_at = utcnow()
            db.add(
                BarrierEvent(
                    barrier_id=barrier.id,
                    event_type="auto_verified",
                    actor="classifier",
                    detail=(
                        f"Refinement pass cleared the "
                        f"{settings.barrier_confidence_threshold} confidence "
                        f"threshold ({deep.confidence:.2f})."
                    ),
                )
            )
            ticket = open_ticket_for_barrier(db, barrier, actor="refinement")
            barrier.ticket_id = ticket.id
        barrier.updated_at = utcnow()
        barrier_service.sync_barrier_edge(db, barrier)
        db.commit()
        logger.info(
            "refinement pass on barrier #%s: conf=%.2f status=%s",
            barrier_id,
            deep.confidence,
            barrier.status,
        )
    except Exception:
        logger.exception("refinement failed for barrier #%s", barrier_id)
        db.rollback()


@media_router.get(
    "/{media_id}",
    summary="Serve a redacted photo straight out of the database",
    response_class=Response,
    description=(
        "Redacted JPEGs are stored as `bytea` in Postgres and streamed from "
        "here; there is no media directory on a serverless filesystem. "
        "`?variant=thumb` returns the small preview."
    ),
)
def get_media(
    media_id: str,
    db: DbSession,
    variant: str = Query(default="full", pattern="^(full|thumb)$"),
) -> Response:
    media = db.get(MediaObject, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail=f"Media '{media_id}' not found")
    payload = media.thumbnail_data if variant == "thumb" else media.data
    if payload is None:
        raise HTTPException(status_code=404, detail="No thumbnail stored for this media object")
    headers = {
        "Cache-Control": "public, max-age=86400, immutable",
        "X-Redacted-Faces": str(media.faces_redacted),
        "X-Redacted-Plates": str(media.plates_redacted),
    }
    return Response(
        content=payload,
        media_type=media.content_type,
        headers=headers,
    )


@router.get("/active", summary="Active barriers as GeoJSON (map layer source)")
def active_barriers(
    db: DbSession,
    min_latitude: float | None = Query(default=None, ge=-90, le=90),
    max_latitude: float | None = Query(default=None, ge=-90, le=90),
    min_longitude: float | None = Query(default=None, ge=-180, le=180),
    max_longitude: float | None = Query(default=None, ge=-180, le=180),
    category: list[str] | None = Query(
        default=None, description="Repeatable: ?category=blocked_ramp&category=broken_lift"
    ),
) -> dict:
    bbox = None
    if None not in (min_latitude, max_latitude, min_longitude, max_longitude):
        bbox = (min_latitude, min_longitude, max_latitude, max_longitude)  # type: ignore[assignment]
    return barrier_service.barriers_feature_collection(
        db, bbox=bbox, categories=category or None
    )


@router.get("/categories", response_model=CategoriesOut, summary="Category catalogue + live counts")
def categories(db: DbSession) -> CategoriesOut:
    rows = barrier_service.active_barriers(db)
    counts: dict[str, int] = {}
    for barrier in rows:
        counts[barrier.category] = counts.get(barrier.category, 0) + 1
    return CategoriesOut(
        categories=[
            CategoryInfo(
                category=category,
                label=CATEGORY_LABELS[category],
                color=CATEGORY_COLORS[category],
                severity=CATEGORY_SEVERITY[category],
                step_free_blocking=category in STEP_FREE_BLOCKING,
                active_count=counts.get(category, 0),
            )
            for category in BARRIER_CATEGORIES
        ]
    )


@router.get("", response_model=BarrierListOut, summary="Paged barrier list with filters")
def list_barriers(
    db: DbSession,
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> BarrierListOut:
    payload = barrier_service.list_barriers(
        db, status=status_filter, category=category, limit=limit, offset=offset
    )
    return BarrierListOut.model_validate(payload)


@router.get("/{barrier_id}", response_model=BarrierOut, summary="Single barrier detail")
def get_barrier(barrier_id: int, db: DbSession) -> BarrierOut:
    barrier = db.get(Barrier, barrier_id)
    if barrier is None:
        raise HTTPException(status_code=404, detail=f"Barrier {barrier_id} not found")
    return BarrierOut.model_validate(barrier.to_dict())


@router.get(
    "/{barrier_id}/timeline",
    response_model=BarrierTimelineOut,
    summary="Audit trail + confirmations for one barrier",
)
def barrier_timeline(barrier_id: int, db: DbSession) -> BarrierTimelineOut:
    barrier = db.get(Barrier, barrier_id)
    if barrier is None:
        raise HTTPException(status_code=404, detail=f"Barrier {barrier_id} not found")
    events = sorted(barrier.events, key=lambda e: e.created_at)
    confirmations = sorted(barrier.confirmations_log, key=lambda c: c.created_at)
    return BarrierTimelineOut(
        barrier_id=barrier.id,
        events=[
            {
                "id": event.id,
                "type": event.event_type,
                "actor": event.actor,
                "detail": event.detail,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
        confirmations=[
            {
                "id": row.id,
                "reporter": row.reporter_label,
                "distance_m": round(row.distance_m, 2),
                "note": row.note,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in confirmations
        ],
    )


@router.post(
    "/{barrier_id}/confirm",
    response_model=BarrierConfirmResponse,
    summary="'Still there' confirmation - triggers consensus auto-verify at 2",
)
def confirm(barrier_id: int, payload: BarrierConfirmRequest, db: DbSession) -> BarrierConfirmResponse:
    try:
        result = barrier_service.confirm_barrier(
            db,
            barrier_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            note=payload.note,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return BarrierConfirmResponse.model_validate(result)


@router.get("/{barrier_id}/edge", summary="The graph edge a barrier is attached to")
def barrier_edge(barrier_id: int, db: DbSession) -> dict:
    barrier = db.get(Barrier, barrier_id)
    if barrier is None:
        raise HTTPException(status_code=404, detail=f"Barrier {barrier_id} not found")
    if not barrier.edge_id:
        return {"barrier_id": barrier.id, "edge": None, "reason": "Report is off the pathway network"}
    edge = db.get(CampusEdge, barrier.edge_id)
    if edge is None:
        return {"barrier_id": barrier.id, "edge": None, "reason": "Edge no longer exists"}
    return {
        "barrier_id": barrier.id,
        "edge": edge.to_geojson()["properties"],
        "weight_explanation": {
            "formula": "weight = distance_m * step_free_penalty * (1 + barrier_multiplier * active_barriers)",
            "barrier_multiplier": settings.barrier_weight_multiplier,
            "hard_blocked": barrier.is_hard_block,
            "source_node": edge.source_node_id,
            "target_node": edge.target_node_id,
            "hard_block_effect": (
                "impassable for wheelchair_accessible=true; 1000x penalty otherwise"
                if barrier.is_hard_block
                else "multiplicative penalty only"
            ),
        },
    }


@router.get("/graph/weights", summary="Current dynamic weight of every edge (debug view)")
def graph_weights(db: DbSession) -> dict:
    graph_service.ensure_loaded(db)
    edges = list(db.scalars(select(CampusEdge)))
    return {
        "barrier_multiplier": settings.barrier_weight_multiplier,
        "formula": "distance_m * step_free_penalty * (1 + multiplier * active_barriers)",
        "edges": [
            {
                "id": edge.id,
                "name": edge.name,
                "kind": edge.kind,
                "is_step_free": edge.is_step_free,
                "distance_m": round(edge.distance_m, 1),
                "active_barriers_count": edge.active_barriers_count,
                "weight": round(edge.weight, 1),
                "step_free_blocked": bool(edge.step_free_blocked),
                "penalised": edge.active_barriers_count > 0,
            }
            for edge in sorted(edges, key=lambda e: e.weight, reverse=True)
        ],
    }
