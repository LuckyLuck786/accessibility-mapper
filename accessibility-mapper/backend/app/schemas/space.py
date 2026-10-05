"""Ghost Space contracts (Pydantic v2).

Validation philosophy
---------------------
Every field a client can influence is bounded: coordinates to real latitude and
longitude, capacities to something a room could plausibly hold, timestamps to
sanity ranges. ``capacity_needed`` is ``>= 1`` so a request for zero seats can
never match every room. ``end_ts`` must be after ``start_ts`` - checked in the
model validator, not in the service, so the client gets a 422 with a useful
message instead of an empty result set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.space_models import (
    BOOKING_STATUSES,
    OCCUPANCY_SOURCES,
    ORGANIZER_TYPES,
    REQUEST_STATUSES,
)


class RoomOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    building: str
    floor: str
    capacity: int
    node_id: str
    is_step_free_access: bool
    has_accessible_features: bool
    power_kw: float
    accessible_notes: str | None = None


class RoomsOut(BaseModel):
    total: int
    step_free_count: int
    buildings: list[str]
    rooms: list[RoomOut]
    energy_note: str = (
        "power_kw is an estimated lighting + HVAC load used for the energy "
        "estimate. It is not metered."
    )


class BookingOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    room_id: str
    organizer_type: str
    title: str
    start_ts: str | None
    end_ts: str | None
    expected_attendees: int
    status: str
    release_reason: str | None = None
    released_at: str | None = None
    reclaimed_at: str | None = None


class BoardBookingOut(BookingOut):
    headcount: int = 0
    state: str
    probability: float = 0.0
    #: The explanation recorded when the engine acted on this booking.
    decision: dict[str, Any] | None = None


class BoardRoomOut(RoomOut):
    bookings: list[BoardBookingOut] = Field(default_factory=list)


class LegendItem(BaseModel):
    state: str
    label: str
    color: str


class BoardOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str
    now: str
    clock: dict[str, Any]
    rooms: list[BoardRoomOut]
    legend: list[LegendItem]
    simulated: bool = True
    simulation_note: str = (
        "Occupancy signals are simulated. Headcount only - no identities, no "
        "cameras, no images."
    )


class BookingsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str
    total: int
    bookings: list[BookingOut]
    simulated: bool = True


class EvidenceOut(BaseModel):
    kind: str
    label: str
    value: float
    detail: str
    source_cell: str | None = None


class ExplanationOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision: str
    probability: float | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    constraints_applied: list[Any] | dict[str, Any] = Field(default_factory=list)
    timestamp: str
    method: str | None = None


class MatchedRoomOut(BaseModel):
    """A room the student can actually take.

    The room itself is nested rather than flattened in: the decision fields sit
    next to it, and flattening would collide on names like ``status``.
    """

    model_config = ConfigDict(extra="allow")

    room: RoomOut
    rank: int = 1
    latitude: float
    longitude: float
    straight_line_m: float
    reasons: list[str] = Field(default_factory=list)
    is_step_free_access: bool = False
    has_accessible_features: bool = False


class ExcludedRoomOut(BaseModel):
    """A room that was ruled out, plus the sentence explaining why.

    ``category`` / ``barrier_id`` are populated only for ``unreachable``: they
    name the specific barrier that severed the route.
    """

    model_config = ConfigDict(extra="allow")

    room: RoomOut
    reason: str
    reason_code: str
    barrier_id: int | None = None
    category: str | None = None
    edge_id: str | None = None
    status: str | None = None
    verified_at: str | None = None
    detail: str | None = None


class SpaceRequestIn(BaseModel):
    """Find a room: seats, window, and whether step-free access is required."""

    capacity_needed: int = Field(default=1, ge=1, le=500)
    start_ts: datetime
    end_ts: datetime
    needs_step_free: bool = False
    origin_latitude: float = Field(..., ge=-90, le=90)
    origin_longitude: float = Field(..., ge=-180, le=180)
    origin_label: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _window_is_ordered(self) -> "SpaceRequestIn":
        if self.end_ts <= self.start_ts:
            raise ValueError("end_ts must be after start_ts")
        duration_h = (self.end_ts - self.start_ts).total_seconds() / 3600
        if duration_h > 12:
            raise ValueError("bookings longer than 12 hours are not supported")
        return self

    @property
    def window_hours(self) -> float:
        return (self.end_ts - self.start_ts).total_seconds() / 3600


class SpaceRequestOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    matched: bool
    needs_step_free: bool
    capacity_needed: int
    window: dict[str, Any]
    origin: dict[str, Any]
    results: list[MatchedRoomOut] = Field(default_factory=list)
    excluded: list[ExcludedRoomOut] = Field(default_factory=list)
    request_id: int | None = None
    explanation: ExplanationOut


class CheckInIn(BaseModel):
    room_id: str = Field(..., min_length=1, max_length=64)
    headcount: int = Field(..., ge=0, le=500)
    booking_id: int | None = Field(default=None, ge=1)


class CheckInOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str
    room: RoomOut
    booking: BookingOut | None = None
    signal: dict[str, Any]
    was_false_release: bool
    timestamp: str
    privacy_note: str = (
        "Headcount only. Ghost Space never stores who was in the room."
    )


class ReclaimIn(BaseModel):
    actor: str | None = Field(default="organizer", max_length=80)


class ReclaimOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str
    booking: BookingOut
    message: str
    decision: dict[str, Any] = Field(default_factory=dict)


class ForceReleaseIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)
    actor: str = "admin"


class ForceReleaseOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    action: str
    booking: BookingOut
    message: str
    decision: dict[str, Any] = Field(default_factory=dict)


class AvailableOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    start: str
    end: str
    capacity_needed: int
    needs_step_free: bool
    count: int
    rooms: list[dict[str, Any]]
    explanation: ExplanationOut


class MetricsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    generated_at: str
    demo_clock: str
    counts: dict[str, Any]
    baseline: dict[str, Any]
    ghost_space: dict[str, Any]
    energy: dict[str, Any]
    releases: dict[str, Any]
    release_accuracy: dict[str, Any]
    requests: dict[str, Any]
    ghost_rate: dict[str, Any]


class SimulateIn(BaseModel):
    actor: str = Field(default="simulator", max_length=80)
    until: datetime | None = None


class SimulateOut(BaseModel):
    signals_created: int
    actor: str
    simulated: bool
    note: str
    timestamp: str


class ClockIn(BaseModel):
    """Control the demo clock. Writes require the admin token."""

    mode: str | None = Field(default=None, pattern="^(live|demo)$")
    speed: float | None = Field(default=None, gt=0, le=600)
    jump_to: datetime | None = None
    playing: bool | None = None
    reset: bool = False


class ClockOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    mode: str
    speed: float
    base: str
    offset_seconds: float
    playing: bool
    now: str
    demo_date: str
    weekday: int
    hour: int
    label: str


class ReleasePassOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    evaluated: int
    released: list[dict[str, Any]] = Field(default_factory=list)
    held: list[dict[str, Any]] = Field(default_factory=list)
    timestamp: str


__all__ = [
    "AvailableOut",
    "BoardOut",
    "BookingsOut",
    "BOOKING_STATUSES",
    "CheckInIn",
    "CheckInOut",
    "ClockIn",
    "ClockOut",
    "ExplanationOut",
    "ForceReleaseIn",
    "ForceReleaseOut",
    "MetricsOut",
    "OCCUPANCY_SOURCES",
    "ORGANIZER_TYPES",
    "ReclaimIn",
    "ReclaimOut",
    "REQUEST_STATUSES",
    "ReleasePassOut",
    "RoomOut",
    "RoomsOut",
    "SimulateIn",
    "SimulateOut",
    "SpaceRequestIn",
    "SpaceRequestOut",
]