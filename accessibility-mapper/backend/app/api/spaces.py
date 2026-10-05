"""Ghost Space endpoints: rooms, availability, matching, check-in, metrics.

Public read-only where it makes sense (rooms, board, availability, metrics);
the mutating admin actions (force release, reclaim override) sit behind the
``X-Admin-Token`` guard.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import AdminGuard, FreshDbSession
from app.core.config import settings
from app.db.space_models import Booking, Room
from app.schemas.space import (
    AvailableOut,
    BoardOut,
    BookingOut,
    BookingsOut,
    CheckInIn,
    CheckInOut,
    ClockIn,
    ClockOut,
    ForceReleaseIn,
    ForceReleaseOut,
    MetricsOut,
    ReclaimIn,
    ReclaimOut,
    ReleasePassOut,
    RoomOut,
    RoomsOut,
    SimulateIn,
    SimulateOut,
    SpaceRequestIn,
    SpaceRequestOut,
)
from app.services import space_service

logger = logging.getLogger("abm.api.spaces")

router = APIRouter(prefix="/spaces", tags=["spaces"])


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@router.get("/rooms", response_model=RoomsOut, summary="Every bookable room")
def list_rooms(db: FreshDbSession) -> RoomsOut:
    rooms = list(db.scalars(select(Room).order_by(Room.building, Room.floor, Room.name)))
    return RoomsOut(
        total=len(rooms),
        step_free_count=sum(1 for r in rooms if r.is_step_free_access),
        buildings=sorted({r.building for r in rooms}),
        rooms=[RoomOut.model_validate(r.to_dict()) for r in rooms],
    )


@router.get("/bookings", response_model=BookingsOut, summary="Bookings for a date")
def list_bookings(
    db: FreshDbSession,
    date: str | None = Query(
        default=None, description="YYYY-MM-DD; defaults to the demo clock's date"
    ),
    room_id: str | None = Query(default=None),
) -> BookingsOut:
    now = space_service.now(db)
    if date:
        try:
            target = datetime.fromisoformat(date).date()
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"date must be YYYY-MM-DD, got '{date}'"
            ) from exc
    else:
        target = now.date()

    start = datetime.combine(target, datetime.min.time(), tzinfo=UTC)
    end = start + timedelta(days=1)

    stmt = select(Booking).where(Booking.start_ts < end, Booking.end_ts > start)
    if room_id:
        stmt = stmt.where(Booking.room_id == room_id)
    bookings = sorted(db.scalars(stmt), key=lambda b: (_aware(b.start_ts), b.room_id))

    return BookingsOut(
        date=target.isoformat(),
        total=len(bookings),
        bookings=[BookingOut.model_validate(b.to_dict()) for b in bookings],
    )


@router.get(
    "/board",
    response_model=BoardOut,
    summary="Timeline board: rooms vs bookings, colour-coded",
)
def ghost_board(
    db: FreshDbSession, date: str | None = Query(default=None)
) -> BoardOut:
    payload = space_service.board(db, date=date)
    return BoardOut.model_validate(payload)


@router.get("/available", response_model=AvailableOut, summary="Rooms free in a window")
def available(
    db: FreshDbSession,
    start: datetime = Query(..., description="ISO 8601"),
    end: datetime = Query(..., description="ISO 8601"),
    capacity: int = Query(default=1, ge=1, le=500),
    needs_step_free: bool = Query(default=False),
) -> AvailableOut:
    start, end = _aware(start), _aware(end)
    if end <= start:
        raise HTTPException(status_code=422, detail="end must be after start")
    rooms = space_service.available_rooms(
        db, start=start, end=end, capacity=capacity, needs_step_free=needs_step_free
    )
    return AvailableOut(
        start=start.isoformat(),
        end=end.isoformat(),
        capacity_needed=capacity,
        needs_step_free=needs_step_free,
        count=len(rooms),
        rooms=[
            {"room": item["room"].to_dict(), "reasons": item["reasons"]} for item in rooms
        ],
        explanation={
            "decision": "found" if rooms else "none",
            "probability": None,
            "constraints_applied": [
                f"capacity >= {capacity}",
                "no conflicting booking in the window",
                *(
                    ["room has step-free access"] if needs_step_free else []
                ),
            ],
            "evidence": [
                {
                    "label": "rooms matching",
                    "value": len(rooms),
                    "detail": "checked against live bookings on the demo clock",
                }
            ],
            "timestamp": space_service.now(db).isoformat(),
        },
    )


@router.post(
    "/request",
    response_model=SpaceRequestOut,
    summary="Find a room that is free AND currently reachable",
    description=(
        "The flagship endpoint. For a step-free request it runs the real A* "
        "router with live barrier penalties and excludes any room whose only "
        "step-free route is currently blocked, naming the barrier responsible."
    ),
)
def request_room(payload: SpaceRequestIn, db: FreshDbSession) -> SpaceRequestOut:
    result = space_service.match_rooms(
        db,
        capacity=payload.capacity_needed,
        start=payload.start_ts,
        end=payload.end_ts,
        needs_step_free=payload.needs_step_free,
        origin_lat=payload.origin_latitude,
        origin_lng=payload.origin_longitude,
        origin_label=payload.origin_label,
    )
    return SpaceRequestOut.model_validate(result)


@router.post(
    "/checkin",
    response_model=CheckInOut,
    summary="Report a headcount at the door (QR check-in)",
    description=(
        "Headcount only. If the room had already been ghost-released and the "
        "organiser now shows up, the release is recorded as a **false release** "
        "so the accuracy metric stays honest."
    ),
)
def checkin(payload: CheckInIn, db: FreshDbSession) -> CheckInOut:
    try:
        result = space_service.check_in(
            db, payload.room_id, payload.headcount, booking_id=payload.booking_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CheckInOut.model_validate(result)


@router.post(
    "/bookings/{booking_id}/reclaim",
    response_model=ReclaimOut,
    summary="Organiser reclaims a released room inside the soft window",
)
def reclaim(booking_id: int, payload: ReclaimIn, db: FreshDbSession) -> ReclaimOut:
    try:
        result = space_service.reclaim_booking(db, booking_id, actor=payload.actor)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ReclaimOut.model_validate(result)


@router.post(
    "/simulate",
    response_model=SimulateOut,
    summary="Generate occupancy signals from the seeded pattern",
    description=(
        "Drives the demo. Emits headcount signals consistent with each seeded "
        "booking's ground truth - rooms marked as ghosts stay at zero, which is "
        "exactly what the release rule keys on."
    ),
)
def simulate(payload: SimulateIn, db: FreshDbSession) -> SimulateOut:
    return SimulateOut.model_validate(
        space_service.simulate_signals(db, until=payload.until, actor=payload.actor)
    )


@router.post(
    "/release-pass",
    response_model=ReleasePassOut,
    summary="Run the release rule over every in-flight booking now",
)
def release_pass(db: FreshDbSession) -> ReleasePassOut:
    return ReleasePassOut.model_validate(space_service.run_release_pass(db))


@router.get(
    "/metrics",
    response_model=MetricsOut,
    summary="BASELINE (no release) vs GHOST SPACE, computed from the data",
)
def metrics(db: FreshDbSession) -> MetricsOut:
    return MetricsOut.model_validate(space_service.metrics(db))


# -----------------------------------------------------------------------
# Admin overrides
# -----------------------------------------------------------------------
admin_router = APIRouter(prefix="/admin/ghost-space", tags=["admin"])


@admin_router.post(
    "/bookings/{booking_id}/force-release",
    response_model=ForceReleaseOut,
    summary="Admin: release a booking regardless of the probability rule",
)
def force_release(
    booking_id: int, payload: ForceReleaseIn, db: FreshDbSession, _user: AdminGuard
) -> ForceReleaseOut:
    try:
        result = space_service.force_release(
            db, booking_id, actor=payload.actor, reason=payload.reason
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return ForceReleaseOut.model_validate(result)


@admin_router.post(
    "/clock",
    response_model=ClockOut,
    summary="Admin: set the demo clock (mode, speed, jump)",
)
def set_clock(
    payload: ClockIn, db: FreshDbSession, _user: AdminGuard
) -> ClockOut:
    clock_in = payload
    try:
        state = space_service.set_clock(
            db,
            mode=clock_in.mode,
            speed=clock_in.speed,
            jump_to=clock_in.jump_to,
            playing=clock_in.playing,
            reset=clock_in.reset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ClockOut.model_validate(state)


__all__ = ["router", "admin_router"]