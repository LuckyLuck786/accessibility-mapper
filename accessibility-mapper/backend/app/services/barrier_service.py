"""Barrier lifecycle: report -> dedupe -> verify -> (graph sync + ticket) -> resolve.

This module is the conductor. It owns the Phase 3.3 duplicate-resolution rule
(a report within 15 m of an active same-category barrier *confirms* it instead
of creating noise), the auto-verification policy, and the Phase 6 analytics
aggregation used by the administrator dashboard.
"""

from __future__ import annotations

import logging
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import (
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    CATEGORY_SEVERITY,
)
from app.core.geo import bounding_box, haversine_m
from app.db.models import (
    Barrier,
    BarrierConfirmation,
    BarrierEvent,
    CampusEdge,
    CampusNode,
    User,
    utcnow,
)
from app.services.cv_service import AnalysisResult, cv_service
from app.services.graph_service import graph_service
from app.services.media_service import clock_now, store_analysis
from app.services.ticket_service import (
    open_ticket_for_barrier,
    resolve_ticket_for_barrier,
    ticket_analytics,
)

logger = logging.getLogger("abm.barriers")

ACTIVE_STATUSES = ("unverified", "verified", "in_progress")

#: Reports whose photo sits this far off the pathway network are still stored
#: but flagged as "off_network" rather than silently snapping to a wrong edge.
OFF_NETWORK_THRESHOLD_M = 30.0


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def submit_report(
    db: Session,
    *,
    image_bytes: bytes | None,
    latitude: float,
    longitude: float,
    filename: str | None = None,
    category_hint: str | None = None,
    description: str | None = None,
    reporter: User | None = None,
    reporter_label: str = "anonymous",
    force_new: bool = False,
    is_public: bool = True,
) -> dict[str, Any]:
    """Ingest a citizen report end-to-end.

    Returns a payload describing what happened: ``created``, ``confirmed``
    (merged into an existing barrier) or ``rejected``, plus the full classifier
    result so the UI can show the detection badge immediately.

    ``is_public`` drives the anti-abuse policy: anonymous reports land as
    ``unverified`` and expire, while a report carrying a valid admin token may
    still auto-verify on classifier confidence alone.
    """
    if image_bytes is None or not image_bytes:
        raise ValueError("A photo is required to submit a barrier report")
    if len(image_bytes) > settings.max_upload_bytes:
        raise ValueError(
            f"Photo is {len(image_bytes) / 1e6:.1f} MB - please send less than "
            f"{settings.max_upload_bytes / 1e6:.1f} MB."
        )

    analysis = cv_service.process(
        image_bytes, note=description, category_hint=category_hint
    )
    stored = store_analysis(db, analysis)

    final_category = category_hint or analysis.category
    if final_category not in CATEGORY_COLORS:
        final_category = analysis.category
    if category_hint:
        detection_source = "citizen_manual"
    else:
        detection_source = analysis.engine

    edge_id, edge_distance, _projected = graph_service.nearest_edge(
        db, latitude, longitude
    )
    off_network = edge_distance > OFF_NETWORK_THRESHOLD_M
    if off_network:
        # Keep the raw GPS fix for the map, but do not poison a path segment.
        edge_id = None

    # --- spatial duplicate resolution ---------------------------------
    if not force_new:
        duplicate = find_duplicate_barrier(db, latitude, longitude, final_category)
        if duplicate is not None:
            return _merge_confirmation(
                db,
                duplicate,
                latitude=latitude,
                longitude=longitude,
                reporter=reporter,
                reporter_label=reporter_label,
                description=description,
                analysis=analysis,
                stored=stored,
                edge_distance=edge_distance,
            )

    confidence = max(analysis.confidence, 0.35 if detection_source == "citizen_manual" else 0.0)
    may_auto_verify = (not is_public) or settings.public_report_auto_verify
    status = (
        "verified"
        if may_auto_verify and confidence >= settings.barrier_confidence_threshold
        else "unverified"
    )
    barrier = Barrier(
        category=final_category,
        latitude=latitude,
        longitude=longitude,
        confidence=confidence,
        status=status,
        severity=CATEGORY_SEVERITY.get(final_category, 3),
        description=description,
        image_path=stored["media_id"],
        thumbnail_path=stored["media_id"],
        redacted_faces=analysis.privacy.faces_redacted,
        redacted_plates=analysis.privacy.plates_redacted,
        detection_source=detection_source,
        detection_boxes=_serialise_detections(analysis),
        edge_id=edge_id,
        reporter_id=reporter.id if reporter else None,
        reporter_label=reporter_label,
        confirmations=0,
        expires_at=Barrier.default_expiry(final_category),
        verified_at=utcnow() if status == "verified" else None,
    )
    db.add(barrier)
    db.flush()

    db.add(
        BarrierEvent(
            barrier_id=barrier.id,
            event_type="created",
            actor=reporter_label,
            detail=(
                f"{CATEGORY_LABELS.get(final_category, final_category)} reported with "
                f"{confidence * 100:.0f}% confidence via {detection_source}; "
                f"{analysis.privacy.total_redactions} privacy region(s) redacted."
            ),
        )
    )
    if status == "verified":
        db.add(
            BarrierEvent(
                barrier_id=barrier.id,
                event_type="auto_verified",
                actor="classifier",
                detail=(
                    f"Confidence {confidence:.2f} >= threshold "
                    f"{settings.barrier_confidence_threshold}."
                ),
            )
        )
    elif is_public:
        db.add(
            BarrierEvent(
                barrier_id=barrier.id,
                event_type="held_for_review",
                actor="public-report-policy",
                detail=(
                    f"Classifier confidence {confidence:.2f} "
                    f"(threshold {settings.barrier_confidence_threshold}) but this is a "
                    f"public report, so it starts unverified and expires "
                    f"{Barrier.default_expiry(final_category).strftime('%Y-%m-%d %H:%M')} UTC "
                    f"unless a citizen or staff member confirms it."
                ),
            )
        )

    sync_barrier_edge(db, barrier)
    ticket = None
    if status == "verified":
        ticket = open_ticket_for_barrier(db, barrier, actor="auto-ticket")
        barrier.ticket_id = ticket.id

    db.commit()
    db.refresh(barrier)

    logger.info(
        "barrier #%s created (%s, %s, conf=%.2f, edge=%s)",
        barrier.id,
        barrier.category,
        barrier.status,
        confidence,
        barrier.edge_id,
    )
    return {
        "action": "created",
        "message": (
            f"New {CATEGORY_LABELS.get(barrier.category, barrier.category).lower()} "
            f"recorded and {'auto-verified' if barrier.status == 'verified' else 'queued for verification'}."
        ),
        "barrier": barrier.to_dict(),
        "cv": analysis.to_dict(),
        "analysis": _analysis_summary(analysis),
        "privacy": analysis.privacy.to_dict(),
        "image": stored,
        "edge": _edge_summary(db, barrier),
        "ticket": ticket.to_dict() if ticket else None,
        "merged_with": None,
        "dedupe": {
            "checked_radius_m": settings.duplicate_radius_m,
            "merged": False,
            "off_network": off_network,
            "snap_distance_m": round(edge_distance, 1),
        },
        "auto_verify": {
            "threshold": settings.barrier_confidence_threshold,
            "confirmations_needed": settings.confirmation_threshold,
            "verified_now": barrier.status == "verified",
            "held_for_public_review": is_public and barrier.status == "unverified",
            "expires_at": barrier.expires_at.isoformat() if barrier.expires_at else None,
        },
    }


def _merge_confirmation(
    db: Session,
    existing: Barrier,
    *,
    latitude: float,
    longitude: float,
    reporter: User | None,
    reporter_label: str,
    description: str | None,
    analysis: AnalysisResult,
    stored: dict[str, Any],
    edge_distance: float,
) -> dict[str, Any]:
    """Fold a nearby same-category report into the existing barrier."""
    distance = haversine_m(latitude, longitude, existing.latitude, existing.longitude)
    existing.confirmations += 1
    existing.confidence = max(existing.confidence, analysis.confidence)
    existing.updated_at = utcnow()
    if description and (not existing.description or len(description) > len(existing.description)):
        existing.description = description
    # A later, sharper photo upgrades the stored evidence.
    if analysis.confidence >= existing.confidence - 0.05:
        existing.image_path = stored["media_id"]
        existing.thumbnail_path = stored["media_id"]
    existing.redacted_faces += analysis.privacy.faces_redacted
    existing.redacted_plates += analysis.privacy.plates_redacted

    db.add(
        BarrierConfirmation(
            barrier_id=existing.id,
            reporter_id=reporter.id if reporter else None,
            reporter_label=reporter_label,
            distance_m=round(distance, 2),
            note=description,
            image_path=stored["media_id"],
        )
    )

    promoted = False
    if (
        existing.status == "unverified"
        and existing.confirmations >= settings.confirmation_threshold
    ):
        existing.status = "verified"
        existing.verified_at = utcnow()
        promoted = True
        db.add(
            BarrierEvent(
                barrier_id=existing.id,
                event_type="verified_by_consensus",
                actor="community",
                detail=(
                    f"{existing.confirmations} independent confirmations within "
                    f"{settings.duplicate_radius_m:.0f} m."
                ),
            )
        )

    db.add(
        BarrierEvent(
            barrier_id=existing.id,
            event_type="confirmed",
            actor=reporter_label,
            detail=(
                f"Corroborated {distance:.1f} m away (total confirmations "
                f"{existing.confirmations})."
            ),
        )
    )

    sync_barrier_edge(db, existing)
    ticket = None
    if existing.status == "verified":
        ticket = open_ticket_for_barrier(db, existing, actor="auto-ticket")
        existing.ticket_id = ticket.id

    db.commit()
    db.refresh(existing)
    return {
        "action": "confirmed",
        "message": (
            f"Already reported {distance:.0f} m away - your report confirms it "
            f"({existing.confirmations} confirmations)."
            + (" Now auto-verified by consensus." if promoted else "")
        ),
        "barrier": existing.to_dict(),
        "cv": analysis.to_dict(),
        "analysis": _analysis_summary(analysis),
        "privacy": analysis.privacy.to_dict(),
        "image": stored,
        "edge": _edge_summary(db, existing),
        "ticket": ticket.to_dict() if ticket else None,
        "merged_with": existing.id,
        "dedupe": {
            "checked_radius_m": settings.duplicate_radius_m,
            "merged": True,
            "duplicate_distance_m": round(distance, 2),
            "promoted_to_verified": promoted,
            "off_network": False,
            "snap_distance_m": round(edge_distance, 1),
        },
        "auto_verify": {
            "threshold": settings.barrier_confidence_threshold,
            "confirmations_needed": settings.confirmation_threshold,
            "verified_now": existing.status == "verified",
        },
    }


def find_duplicate_barrier(
    db: Session, latitude: float, longitude: float, category: str
) -> Barrier | None:
    """Nearest active barrier of the same category inside the dedupe radius.

    Uses an index-friendly bounding-box pre-filter, then exact haversine maths.
    On PostGIS deployments the same query can be served by ``ST_DWithin`` on the
    GiST-indexed ``geom`` column (see ``app.core.database.POSTGIS_DDL``).
    """
    min_lat, min_lng, max_lat, max_lng = bounding_box(
        latitude, longitude, settings.duplicate_radius_m
    )
    rows = db.scalars(
        select(Barrier)
        .where(
            Barrier.category == category,
            Barrier.status.in_(ACTIVE_STATUSES),
            Barrier.latitude.between(min_lat, max_lat),
            Barrier.longitude.between(min_lng, max_lng),
        )
        .order_by(Barrier.created_at.desc())
        .limit(25)
    )
    best, best_distance = None, math.inf
    for barrier in rows:
        if not barrier.is_active:
            continue
        distance = haversine_m(latitude, longitude, barrier.latitude, barrier.longitude)
        if distance <= settings.duplicate_radius_m and distance < best_distance:
            best, best_distance = barrier, distance
    return best


def confirm_barrier(
    db: Session,
    barrier_id: int,
    *,
    reporter: User | None = None,
    reporter_label: str = "anonymous",
    latitude: float | None = None,
    longitude: float | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Explicit 'still broken' confirmation from the map (no photo required)."""
    barrier = db.get(Barrier, barrier_id)
    if barrier is None:
        raise LookupError(f"Barrier {barrier_id} not found")
    if barrier.status == "resolved":
        raise ValueError("This barrier is already resolved")

    distance = (
        haversine_m(latitude, longitude, barrier.latitude, barrier.longitude)
        if latitude is not None and longitude is not None
        else 0.0
    )
    barrier.confirmations += 1
    barrier.updated_at = utcnow()
    db.add(
        BarrierConfirmation(
            barrier_id=barrier.id,
            reporter_id=reporter.id if reporter else None,
            reporter_label=reporter_label,
            distance_m=round(distance, 2),
            note=note,
        )
    )

    promoted = False
    if (
        barrier.status == "unverified"
        and barrier.confirmations >= settings.confirmation_threshold
    ):
        barrier.status = "verified"
        barrier.verified_at = utcnow()
        promoted = True
    if barrier.status == "verified":
        barrier.verified_at = barrier.verified_at or utcnow()

    db.add(
        BarrierEvent(
            barrier_id=barrier.id,
            event_type="verified_by_consensus" if promoted else "confirmed",
            actor=reporter_label,
            detail=(
                f"Consensus reached: {barrier.confirmations} confirmations."
                if promoted
                else f"Citizen confirmation #{barrier.confirmations}."
            ),
        )
    )

    sync_barrier_edge(db, barrier)
    ticket = None
    if barrier.status in ("verified", "in_progress"):
        ticket = open_ticket_for_barrier(db, barrier, actor="auto-ticket")
        barrier.ticket_id = ticket.id

    db.commit()
    db.refresh(barrier)
    return {
        "action": "confirmed",
        "message": (
            f"Thanks - that is confirmation #{barrier.confirmations}."
            + (" It is now verified and on the facilities queue." if promoted else "")
        ),
        "barrier": barrier.to_dict(),
        "promoted_to_verified": promoted,
        "ticket": ticket.to_dict() if ticket else None,
    }


def resolve_barrier(
    db: Session,
    barrier_id: int,
    *,
    actor: str = "admin",
    resolution_note: str | None = None,
) -> dict[str, Any]:
    """Mark a barrier resolved: drop the penalty, close the ticket, update map."""
    barrier = db.get(Barrier, barrier_id)
    if barrier is None:
        raise LookupError(f"Barrier {barrier_id} not found")

    barrier.status = "resolved"
    barrier.resolved_at = utcnow()
    barrier.updated_at = utcnow()
    if resolution_note:
        barrier.description = (
            f"{barrier.description}\n[Resolved] {resolution_note}"
            if barrier.description
            else f"[Resolved] {resolution_note}"
        )

    db.add(
        BarrierEvent(
            barrier_id=barrier.id,
            event_type="resolved",
            actor=actor,
            detail=resolution_note or "Marked resolved from the facilities dashboard.",
        )
    )
    ticket = resolve_ticket_for_barrier(db, barrier, actor=actor)
    sync = sync_barrier_edge(db, barrier)
    db.commit()
    db.refresh(barrier)

    return {
        "action": "resolved",
        "message": (
            f"{barrier.label} resolved in "
            f"{barrier.resolution_hours or 0:.1f} h. Path penalty cleared."
        ),
        "barrier": barrier.to_dict(),
        "ticket": ticket.to_dict() if ticket else None,
        "graph": sync,
    }


def reopen_barrier(
    db: Session,
    barrier_id: int,
    *,
    actor: str = "admin",
    reason: str | None = None,
) -> dict[str, Any]:
    """Re-assert a barrier that came back after being 'fixed'.

    Real-world maintenance frequently fails on the first attempt: contractors
    move the obstruction and it reappears the same week. Reopening restores the
    penalty, reopens the work order and records the recurrence, which is what
    feeds the dashboard's recurring-hotspot analytics.
    """
    barrier = db.get(Barrier, barrier_id)
    if barrier is None:
        raise LookupError(f"Barrier {barrier_id} not found")

    barrier.status = "verified"
    barrier.resolved_at = None
    barrier.updated_at = utcnow()
    barrier.expires_at = Barrier.default_expiry(barrier.category)

    db.add(
        BarrierEvent(
            barrier_id=barrier.id,
            event_type="reopened",
            actor=actor,
            detail=reason or "Barrier re-asserted from the facilities dashboard.",
        )
    )
    ticket = open_ticket_for_barrier(db, barrier, actor=actor)
    barrier.ticket_id = ticket.id
    sync = sync_barrier_edge(db, barrier)
    db.commit()
    db.refresh(barrier)

    return {
        "action": "reopened",
        "message": (
            f"{barrier.label} re-opened on {ticket.code} - dynamic path penalty restored."
        ),
        "barrier": barrier.to_dict(),
        "ticket": ticket.to_dict(),
        "graph": sync,
    }


def expire_stale_barriers(db: Session) -> int:
    """Housekeeping sweep: lapse stale unconfirmed reports so the map self-heals."""
    rows = db.scalars(
        select(Barrier).where(Barrier.status.in_(ACTIVE_STATUSES))
    )
    expired = 0
    touched_edges: set[str] = set()
    for barrier in rows:
        if barrier.expires_at and Barrier._aware(barrier.expires_at) < utcnow():
            barrier.status = "expired"
            barrier.updated_at = utcnow()
            expired += 1
            if barrier.edge_id:
                touched_edges.add(barrier.edge_id)
            db.add(
                BarrierEvent(
                    barrier_id=barrier.id,
                    event_type="expired",
                    actor="scheduler",
                    detail="Report lapsed without confirmation.",
                )
            )
    if expired:
        graph_service.sync_barrier_penalties(db, touched_edges)
        db.commit()
        logger.info("expired %s stale barriers", expired)
    return expired


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
def active_barriers(
    db: Session,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    categories: Sequence[str] | None = None,
    include_resolved_recent_hours: int | None = None,
) -> list[Barrier]:
    stmt = select(Barrier)
    if bbox:
        min_lat, min_lng, max_lat, max_lng = bbox
        stmt = stmt.where(
            Barrier.latitude.between(min_lat, max_lat),
            Barrier.longitude.between(min_lng, max_lng),
        )
    if categories:
        stmt = stmt.where(Barrier.category.in_(list(categories)))

    if include_resolved_recent_hours:
        cutoff = utcnow() - timedelta(hours=include_resolved_recent_hours)
        stmt = stmt.where(
            (Barrier.status.in_(ACTIVE_STATUSES))
            | ((Barrier.status == "resolved") & (Barrier.resolved_at >= cutoff))
        )
    else:
        stmt = stmt.where(Barrier.status.in_(ACTIVE_STATUSES))

    rows = list(db.scalars(stmt.order_by(Barrier.created_at.desc())))
    return [b for b in rows if b.is_active or b.status == "resolved"]


def barriers_feature_collection(
    db: Session,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    categories: Sequence[str] | None = None,
) -> dict[str, Any]:
    barriers = active_barriers(db, bbox=bbox, categories=categories)
    return {
        "type": "FeatureCollection",
        "features": [b.to_geojson() for b in barriers],
        "meta": {
            "count": len(barriers),
            "generated_at": utcnow().isoformat(),
            "categories": sorted({b.category for b in barriers}),
            "verified": sum(1 for b in barriers if b.status == "verified"),
            "unverified": sum(1 for b in barriers if b.status == "unverified"),
            "in_progress": sum(1 for b in barriers if b.status == "in_progress"),
        },
    }


def campus_network_geojson(db: Session, *, include_nodes: bool = True) -> dict[str, Any]:
    graph_service.ensure_loaded(db)
    edges = list(db.scalars(select(CampusEdge)))
    features = [edge.to_geojson() for edge in edges]
    if include_nodes:
        features += [node.to_geojson() for node in db.scalars(select(CampusNode))]
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "nodes": sum(1 for f in features if f["geometry"]["type"] == "Point"),
            "edges": sum(1 for f in features if f["geometry"]["type"] == "LineString"),
            "step_free_edges": sum(
                1
                for edge in edges
                if edge.is_step_free
            ),
            "generated_at": utcnow().isoformat(),
        },
    }


# ---------------------------------------------------------------------------
# Phase 6 - analytics
# ---------------------------------------------------------------------------
def analytics(db: Session) -> dict[str, Any]:
    barriers = list(db.scalars(select(Barrier)))
    now = utcnow()
    active = [b for b in barriers if b.is_active]
    resolved = [b for b in barriers if b.status == "resolved" and b.resolved_at]

    resolution_hours = [
        (Barrier._aware(b.resolved_at) - Barrier._aware(b.created_at)).total_seconds() / 3600.0
        for b in resolved
    ]
    created_7d = [
        b for b in barriers if (now - Barrier._aware(b.created_at)).days < 7
    ]
    resolved_7d = [
        b
        for b in resolved
        if (now - Barrier._aware(b.resolved_at)).days < 7
    ]
    auto_verified = [b for b in barriers if b.verified_at and b.confirmations == 0]
    consensus = [b for b in barriers if b.confirmations > 0]

    category_rows: list[dict[str, Any]] = []
    for category in CATEGORY_LABELS:
        group = [b for b in barriers if b.category == category]
        if not group:
            continue
        group_resolved = [b for b in group if b.status == "resolved" and b.resolved_at]
        hours = [
            (Barrier._aware(b.resolved_at) - Barrier._aware(b.created_at)).total_seconds() / 3600.0
            for b in group_resolved
        ]
        category_rows.append(
            {
                "category": category,
                "label": CATEGORY_LABELS[category],
                "color": CATEGORY_COLORS[category],
                "severity": CATEGORY_SEVERITY.get(category, 3),
                "total": len(group),
                "active": sum(1 for b in group if b.is_active),
                "resolved": len(group_resolved),
                "avg_resolution_hours": round(sum(hours) / len(hours), 2) if hours else None,
                "confirmations": sum(b.confirmations for b in group),
                "avg_confidence": round(sum(b.confidence for b in group) / len(group), 3),
                "priority_weight": round(
                    sum(CATEGORY_SEVERITY.get(b.category, 3) for b in group if b.is_active)
                    / max(1, sum(1 for b in group if b.is_active)),
                    2,
                ),
            }
        )
    category_rows.sort(key=lambda row: (row["active"], row["severity"]), reverse=True)

    heatmap, hotspots = _heatmap(db, barriers)
    edge = db.scalar(select(CampusEdge).limit(1))
    network = graph_service.stats(db) if edge is not None else {}

    return {
        "generated_at": now.isoformat(),
        "kpis": {
            "total_barriers": len(barriers),
            "active_barriers": len(active),
            "verified_active": sum(1 for b in active if b.status == "verified"),
            "unverified_active": sum(1 for b in active if b.status == "unverified"),
            "in_progress": sum(1 for b in active if b.status == "in_progress"),
            "resolved_total": len(resolved),
            "created_last_7d": len(created_7d),
            "resolved_last_7d": len(resolved_7d),
            "avg_resolution_hours": (
                round(sum(resolution_hours) / len(resolution_hours), 2)
                if resolution_hours
                else None
            ),
            "median_resolution_hours": _median(resolution_hours),
            "avg_confirmations_per_barrier": (
                round(sum(b.confirmations for b in barriers) / len(barriers), 2) if barriers else 0.0
            ),
            "auto_verified_share": (
                round(len(auto_verified) / len(barriers), 3) if barriers else 0.0
            ),
            "consensus_verified_share": (
                round(len(consensus) / len(barriers), 3) if barriers else 0.0
            ),
            "privacy_redactions": sum(
                b.redacted_faces + b.redacted_plates for b in barriers
            ),
            "faces_redacted": sum(b.redacted_faces for b in barriers),
            "plates_redacted": sum(b.redacted_plates for b in barriers),
            "cv_engine": cv_service.engine_name,
        },
        "category_breakdown": category_rows,
        "heatmap": heatmap,
        "hotspot_zones": hotspots,
        "resolution_trend": _resolution_trend(barriers),
        "tickets": ticket_analytics(db),
        "routing_health": _routing_health(db, network, active),
        "recent_reports": [
            b.to_dict()
            for b in sorted(barriers, key=lambda b: Barrier._aware(b.created_at), reverse=True)[:12]
        ],
        "status_mix": dict(Counter(b.status for b in barriers)),
    }


def _heatmap(db: Session, barriers: list[Barrier]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Grid-cluster barriers into severity-weighted heat points + named zones.

    ~40 m cells: fine enough to separate opposite sides of a quad, coarse
    enough that five reports about the same doorway collapse into one hot spot.
    """
    cell_size = 0.00036  # ≈ 40 m of latitude
    cells: dict[tuple[int, int], list[Barrier]] = defaultdict(list)
    for barrier in barriers:
        if barrier.status == "expired":
            continue
        key = (round(barrier.latitude / cell_size), round(barrier.longitude / cell_size))
        cells[key].append(barrier)

    edge_names = {e.id: e.name for e in db.scalars(select(CampusEdge))}
    heat: list[dict[str, Any]] = []
    for key, group in cells.items():
        lat = sum(b.latitude for b in group) / len(group)
        lng = sum(b.longitude for b in group) / len(group)
        active = [b for b in group if b.is_active]
        intensity = sum(
            CATEGORY_SEVERITY.get(b.category, 3) * (1.0 + 0.15 * b.confirmations)
            for b in active
        )
        if intensity <= 0:
            intensity = 0.4 * len(group)
        dominant = Counter(b.category for b in group).most_common(1)[0][0]
        edge_ids = [b.edge_id for b in group if b.edge_id]
        heat.append(
            {
                "latitude": round(lat, 6),
                "longitude": round(lng, 6),
                "intensity": round(intensity, 2),
                "count": len(group),
                "active_count": len(active),
                "resolved_count": len(group) - len(active),
                "dominant_category": dominant,
                "dominant_label": CATEGORY_LABELS.get(dominant, dominant),
                "categories": dict(Counter(b.category for b in group)),
                "location_name": edge_names.get(edge_ids[0]) if edge_ids else None,
                "recurring": len(group) >= 3,
            }
        )
    heat.sort(key=lambda point: point["intensity"], reverse=True)

    hotspots = [
        {
            "name": point["location_name"] or "Unmapped segment",
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "incidents": point["count"],
            "active": point["active_count"],
            "intensity": point["intensity"],
            "dominant_category": point["dominant_category"],
            "dominant_label": point["dominant_label"],
            "recurring": point["recurring"],
        }
        for point in heat[:8]
    ]
    return heat, hotspots


def _resolution_trend(barriers: list[Barrier], days: int = 14) -> list[dict[str, Any]]:
    today = utcnow().date()
    trend: list[dict[str, Any]] = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        created = sum(
            1 for b in barriers if Barrier._aware(b.created_at).date() == day
        )
        resolved = sum(
            1
            for b in barriers
            if b.resolved_at and Barrier._aware(b.resolved_at).date() == day
        )
        trend.append({"date": day.isoformat(), "created": created, "resolved": resolved})
    return trend


def _routing_health(db: Session, network: dict[str, Any], active: list[Barrier]) -> dict[str, Any]:
    blocked_edges = sorted({b.edge_id for b in active if b.is_hard_block and b.edge_id})
    affected_edges = sorted({b.edge_id for b in active if b.edge_id})
    step_free_nodes = int(network.get("nodes") or 0)
    return {
        "network": network,
        "blocked_step_free_edges": blocked_edges,
        "affected_edges": affected_edges,
        "affected_edge_count": len(affected_edges),
        "affected_edge_share": (
            round(len(affected_edges) / max(1, int(network.get("edges") or 1)), 3)
        ),
        "step_free_coverage": (
            round(float(network.get("step_free_edges", 0)) / max(1, int(network.get("edges") or 1)), 3)
        ),
        "isolated_step_free_zones": int(network.get("isolated_step_free_zones") or 0),
        "nodes": step_free_nodes,
        "algorithm": network.get("algorithm"),
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[mid], 2)
    return round((ordered[mid - 1] + ordered[mid]) / 2.0, 2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def sync_barrier_edge(db: Session, barrier: Barrier) -> dict[str, Any]:
    """Recompute dynamic weights for the edge this barrier sits on.

    Also bumps the shared ``graph_version`` row so every other (stateless)
    function instance knows to rebuild its cached NetworkX graph before serving
    the next request. Without this, a warm instance would keep routing around a
    barrier that has just been resolved.
    """
    return graph_service.sync_barrier_penalties(db, [barrier.edge_id])


def _serialise_detections(analysis: AnalysisResult) -> str:
    import json

    return json.dumps([d.to_dict() for d in analysis.detections])


def _analysis_summary(analysis: AnalysisResult) -> dict[str, Any]:
    return {
        "category": analysis.category,
        "label": CATEGORY_LABELS.get(analysis.category, analysis.category),
        "confidence": round(analysis.confidence, 3),
        "engine": analysis.engine,
        "would_auto_verify": analysis.confidence >= settings.barrier_confidence_threshold,
        "notes": analysis.notes,
        "counts": {
            "faces": analysis.privacy.faces_redacted,
            "plates": analysis.privacy.plates_redacted,
        },
    }


def _edge_summary(db: Session, barrier: Barrier) -> dict[str, Any] | None:
    if not barrier.edge_id:
        return None
    edge = db.get(CampusEdge, barrier.edge_id)
    if edge is None:
        return None
    return {
        "id": edge.id,
        "name": edge.name,
        "kind": edge.kind,
        "is_step_free": edge.is_step_free,
        "active_barriers_count": edge.active_barriers_count,
        "weight": round(edge.weight, 2),
        "distance_m": round(edge.distance_m, 1),
    }


def list_barriers(
    db: Session,
    *,
    status: str | None = None,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(Barrier)
    if status:
        stmt = stmt.where(Barrier.status == status)
    if category:
        stmt = stmt.where(Barrier.category == category)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = list(
        db.scalars(
            stmt.order_by(Barrier.created_at.desc()).offset(offset).limit(limit)
        )
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [b.to_dict() for b in rows],
    }
