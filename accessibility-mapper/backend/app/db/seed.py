"""Phase 1 - seed the campus network + demo barriers.

Idempotent: ``seed_if_empty`` only runs when the ``nodes`` table is empty.
``seed(reset=True)`` wipes and rebuilds, which is what the ``make seed``
convenience target and the test-suite use.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import CATEGORY_SEVERITY
from app.core.geo import haversine_m
from app.core.security import hash_password
from app.db.campus_data import BARRIER_SCENARIOS, EDGES, NODES, PRESET_DESTINATIONS, USERS
from app.db.models import (
    AppState,
    Barrier,
    BarrierConfirmation,
    BarrierEvent,
    CampusEdge,
    CampusNode,
    MaintenanceTicket,
    ReportCounter,
    User,
    utcnow,
)
from app.db.space_models import Booking, NoShowStat, OccupancySignal, Room, SpaceRequest
from app.db.space_seed_data import BOOKINGS, NOSHOW_HISTORY, ROOMS
from app.services.graph_service import graph_service
from app.services.ticket_service import open_ticket_for_barrier

logger = logging.getLogger("abm.seed")


def seed_if_empty(db: Session) -> bool:
    """Populate demo data when the database is brand new."""
    existing = db.scalar(select(func.count(CampusNode.id)))
    if existing:
        logger.info("database already seeded (%s nodes) - skipping", existing)
        graph_service.invalidate()
        graph_service.ensure_loaded(db)
        return False
    seed(db)
    return True


def seed(db: Session, *, reset: bool = False) -> dict[str, int]:
    if reset:
        _wipe(db)

    now = utcnow()
    users = _seed_users(db, now)
    nodes = _seed_nodes(db)
    edges = _seed_edges(db, nodes)
    barriers, confirmations = _seed_barriers(db, edges, nodes, users, now)

    db.flush()
    # Materialise dynamic edge weights before tickets are scored, so impact
    # estimates already account for the seeded barrier penalties. The graph is
    # loaded first, then every seeded barrier edge is re-synced so
    # ``active_barriers_count`` (and therefore the weight) reflects the demo
    # scenario from the very first request.
    graph_service.invalidate()
    graph_service.recompute_weights(db)
    graph_service.sync_barrier_penalties(db, [b.edge_id for b in barriers])

    tickets = 0
    for barrier in barriers:
        if barrier.status in ("verified", "in_progress"):
            open_ticket_for_barrier(db, barrier, actor="seed")
            tickets += 1

    # Seed a second confirmation row for barriers that claim multiple
    # confirmations, so the audit trail matches the counters.
    for barrier in barriers:
        recorded = sum(1 for c in confirmations if c.barrier_id == barrier.id)
        for index in range(max(0, barrier.confirmations - recorded)):
            db.add(
                BarrierConfirmation(
                    barrier_id=barrier.id,
                    reporter_label=f"citizen-{index + 1}@campus.edu",
                    distance_m=round(3.5 + index * 2.0, 2),
                    note="Still obstructed when I passed.",
                    created_at=now - timedelta(hours=max(0.5, barrier.age_hours - index)),
                )
            )

    db.commit()
    graph_service.invalidate()
    graph_service.recompute_weights(db)
    graph_service.sync_barrier_penalties(db, [b.edge_id for b in barriers])
    db.commit()

    ghost = _seed_spaces(db, nodes)
    # Ghost Space is seeded last and must be committed in its own right: the
    # barrier phase above already committed, so without this the rooms and
    # bookings would be rolled back when the session closed.
    db.commit()

    counts = {
        "users": len(users),
        "nodes": len(nodes),
        "edges": len(edges),
        "barriers": len(barriers),
        "tickets": tickets,
        **ghost,
    }
    logger.info("seed complete: %s", counts)
    return counts


def _seed_spaces(db: Session, nodes: dict[str, CampusNode]) -> dict[str, int]:
    """Rooms, one realistic day of bookings (~30% ghosts), and no-show history."""
    existing = db.scalar(select(func.count(Room.id)))
    if existing:
        logger.info("Ghost Space already seeded (%s rooms) - skipping", existing)
        return {"rooms": existing, "bookings": 0, "noshow_cells": 0}

    missing = [room["node_id"] for room in ROOMS if room["node_id"] not in nodes]
    if missing:
        raise ValueError(f"room specs reference unknown graph nodes: {sorted(set(missing))}")

    for spec in ROOMS:
        db.add(Room(**spec))
    db.flush()

    # Booking offsets are minutes after midnight on the demo day.
    day = _space_demo_day()
    for spec in BOOKINGS:
        start = day + timedelta(minutes=int(spec["start"]))
        end = day + timedelta(minutes=int(spec["end"]))
        db.add(
            Booking(
                room_id=spec["room"],
                organizer_type=spec["organizer"],
                title=spec["title"],
                start_ts=start,
                end_ts=end,
                expected_attendees=int(spec["attendees"]),
                status="active",
                simulated_will_show=bool(spec["will_show"]),
            )
        )
    db.flush()

    for organizer_type, weekday, hour, bookings_count, noshow_count in NOSHOW_HISTORY:
        db.add(
            NoShowStat(
                organizer_type=organizer_type,
                weekday=weekday,
                hour=hour,
                bookings_count=bookings_count,
                noshow_count=noshow_count,
            )
        )
    db.flush()

    # Headcount signals consistent with each booking's ground truth: ghosts stay
    # at zero (that is the evidence the release rule keys on), real bookings
    # check in shortly after they start.
    for booking in db.scalars(select(Booking)):
        if booking.simulated_will_show:
            db.add(
                OccupancySignal(
                    room_id=booking.room_id,
                    booking_id=booking.id,
                    ts=booking.start_ts + timedelta(minutes=1),
                    headcount=max(1, int(round(booking.expected_attendees * 0.8))),
                    source="simulated_sensor",
                    simulated=True,
                )
            )
        else:
            db.add(
                OccupancySignal(
                    room_id=booking.room_id,
                    booking_id=booking.id,
                    ts=booking.start_ts + timedelta(minutes=2),
                    headcount=0,
                    source="simulated_sensor",
                    simulated=True,
                )
            )
    db.flush()

    ghosts = sum(1 for spec in BOOKINGS if not spec["will_show"])
    counts = {
        "rooms": len(ROOMS),
        "bookings": len(BOOKINGS),
        "ghost_bookings": ghosts,
        "noshow_cells": len(NOSHOW_HISTORY),
    }
    logger.info(
        "seeded Ghost Space: %s rooms, %s bookings (%s ghost = %.0f%%)",
        counts["rooms"],
        counts["bookings"],
        ghosts,
        100.0 * ghosts / max(1, counts["bookings"]),
    )
    return counts


def _space_demo_day() -> datetime:
    """Midnight UTC on the configured demo day (a weekday)."""
    if settings.ghost_demo_date:
        return datetime.combine(
            datetime.fromisoformat(settings.ghost_demo_date).date(),
            datetime.min.time(),
            tzinfo=UTC,
        )
    day = datetime.now(UTC).date()
    for _ in range(7):
        if day.weekday() < 5:
            break
        day -= timedelta(days=1)
    return datetime.combine(day, datetime.min.time(), tzinfo=UTC)


def _wipe(db: Session) -> None:
    for model in (
        OccupancySignal,
        SpaceRequest,
        Booking,
        Room,
        NoShowStat,
        ReportCounter,
        MaintenanceTicket,
        BarrierEvent,
        BarrierConfirmation,
        Barrier,
        CampusEdge,
        CampusNode,
        User,
    ):
        db.execute(delete(model))
    db.commit()
    # Reset the graph version handshake along with the data it describes.
    state = db.get(AppState, "graph_version")
    if state is not None:
        db.execute(delete(AppState))
    db.commit()
    logger.info("existing demo data removed")


def _seed_users(db: Session, now) -> dict[str, User]:
    out: dict[str, User] = {}
    for spec in USERS:
        user = User(
            email=spec["email"],
            full_name=spec["full_name"],
            role=spec["role"],
            password_hash=hash_password(spec["password"]),
            created_at=now - timedelta(days=180),
        )
        db.add(user)
        out[spec["email"]] = user
    db.flush()
    return out


def _seed_nodes(db: Session) -> dict[str, CampusNode]:
    nodes: dict[str, CampusNode] = {}
    for spec in NODES:
        node = CampusNode(
            id=spec["id"],
            name=spec["name"],
            kind=spec.get("kind", "intersection"),
            latitude=spec["latitude"],
            longitude=spec["longitude"],
            has_elevator=spec.get("has_elevator", False),
            is_entrance=spec.get("is_entrance", False),
            is_step_free=spec.get("is_step_free", True),
            building_code=spec.get("building_code"),
            accessible_notes=spec.get("accessible_notes"),
            campus_zone=spec.get("campus_zone"),
        )
        db.add(node)
        nodes[node.id] = node
    db.flush()
    logger.info("seeded %s campus nodes", len(nodes))
    return nodes


def _seed_edges(db: Session, nodes: dict[str, CampusNode]) -> dict[str, CampusEdge]:
    edges: dict[str, CampusEdge] = {}
    missing: list[str] = []
    for spec in EDGES:
        source = nodes.get(spec["source"])
        target = nodes.get(spec["target"])
        if source is None or target is None:
            missing.append(spec["id"])
            continue
        distance = haversine_m(
            source.latitude, source.longitude, target.latitude, target.longitude
        )
        edge = CampusEdge(
            id=spec["id"],
            name=spec["name"],
            kind=spec.get("kind", "footpath"),
            source_node_id=source.id,
            target_node_id=target.id,
            distance_m=round(distance, 2),
            is_step_free=spec.get("is_step_free", True),
            width_m=spec.get("width_m", 2.5),
            incline_pct=spec.get("incline_pct", 0.0),
            traffic_weight=spec.get("traffic_weight", 0.5),
            active_barriers_count=0,
            weight=round(distance, 2),
        )
        db.add(edge)
        edges[edge.id] = edge
    if missing:
        raise ValueError(f"edge specs reference unknown nodes: {missing}")
    db.flush()
    logger.info("seeded %s campus edges (distances derived by haversine)", len(edges))
    return edges


def _seed_barriers(
    db: Session,
    edges: dict[str, CampusEdge],
    nodes: dict[str, CampusNode],
    users: dict[str, User],
    now,
) -> tuple[list[Barrier], list[BarrierConfirmation]]:
    barriers: list[Barrier] = []
    confirmations: list[BarrierConfirmation] = []
    for spec in BARRIER_SCENARIOS:
        edge = edges.get(spec["edge_id"])
        if edge is None:
            logger.warning("skipping barrier scenario %s: unknown edge", spec["slug"])
            continue
        source = nodes[edge.source_node_id]
        target = nodes[edge.target_node_id]
        mid_lat = (source.latitude + target.latitude) / 2.0
        mid_lng = (source.longitude + target.longitude) / 2.0
        created_at = now - timedelta(hours=spec["offset_hours"])

        resolved_after = spec.get("resolved_after_hours")
        resolved_at = (
            created_at + timedelta(hours=resolved_after) if resolved_after else None
        )

        # Historic resolved reports still influence edge weights until the
        # graph is recomputed, so they are stored inactive from the start.
        barrier = Barrier(
            category=spec["category"],
            latitude=round(mid_lat + spec.get("latitude_offset", 0.0), 6),
            longitude=round(mid_lng + spec.get("longitude_offset", 0.0), 6),
            confidence=spec["confidence"],
            status=spec["status"],
            severity=CATEGORY_SEVERITY.get(spec["category"], 3),
            description=spec["description"],
            detection_source=spec.get("detection_source", "heuristic"),
            edge_id=edge.id,
            reporter_id=None,
            reporter_label=spec.get("reporter_label", "anonymous"),
            confirmations=spec["confirmations"],
            created_at=created_at,
            updated_at=resolved_at or created_at,
            verified_at=created_at if spec["status"] != "unverified" else None,
            resolved_at=resolved_at,
            expires_at=Barrier.default_expiry(spec["category"], from_time=created_at),
            redacted_faces=1 if spec["category"] in ("obstacle", "blocked_ramp") else 0,
            redacted_plates=1 if spec["category"] in ("blocked_ramp", "construction") else 0,
        )
        db.add(barrier)
        db.flush()
        barriers.append(barrier)

        db.add(
            BarrierEvent(
                barrier_id=barrier.id,
                event_type="created",
                actor=barrier.reporter_label,
                detail=f"Seeded demo report: {spec['description'][:90]}",
                created_at=created_at,
            )
        )
        if spec.get("auto_verify_reason"):
            db.add(
                BarrierEvent(
                    barrier_id=barrier.id,
                    event_type="auto_verified",
                    actor="cv-pipeline",
                    detail=spec["auto_verify_reason"],
                    created_at=created_at + timedelta(minutes=4),
                )
            )
        if resolved_at:
            db.add(
                BarrierEvent(
                    barrier_id=barrier.id,
                    event_type="resolved",
                    actor="facilities@campus.edu",
                    detail=spec.get("resolution_note", "Resolved by facilities."),
                    created_at=resolved_at,
                )
            )

        if spec["confirmations"]:
            confirmations.append(
                BarrierConfirmation(
                    barrier_id=barrier.id,
                    reporter_id=users["demo@campus.edu"].id,
                    reporter_label=users["demo@campus.edu"].email,
                    distance_m=6.4,
                    note="Confirmed on my way to class.",
                    created_at=created_at + timedelta(minutes=25),
                )
            )

    db.flush()
    logger.info(
        "seeded %s barrier reports (%s currently active)",
        len(barriers),
        sum(1 for b in barriers if b.status in ("verified", "unverified", "in_progress")),
    )
    return barriers, confirmations


def preset_destinations(db: Session) -> list[dict]:
    """Quick-pick destinations for the route planner, enriched with coordinates."""
    out = []
    for preset in PRESET_DESTINATIONS:
        node = db.get(CampusNode, preset["node_id"])
        if node is None:
            continue
        out.append(
            preset
            | {
                "name": node.name,
                "latitude": node.latitude,
                "longitude": node.longitude,
                "has_elevator": node.has_elevator,
                "is_step_free": node.is_step_free,
                "campus_zone": node.campus_zone,
            }
        )
    return out


def campus_bounds(db: Session) -> dict[str, float] | None:
    nodes = list(db.scalars(select(CampusNode)))
    if not nodes:
        return None
    lats = [n.latitude for n in nodes]
    lngs = [n.longitude for n in nodes]
    return {
        "min_latitude": min(lats),
        "max_latitude": max(lats),
        "min_longitude": min(lngs),
        "max_longitude": max(lngs),
        "center_latitude": (min(lats) + max(lats)) / 2,
        "center_longitude": (min(lngs) + max(lngs)) / 2,
    }


__all__ = ["seed", "seed_if_empty", "preset_destinations", "campus_bounds", "settings"]
