"""Phase 1 - Ghost Space data model.

Five tables, deliberately boring:

``rooms``
    Physical teaching/meeting rooms, each bound to a campus **graph node** so
    reachability can be answered by the real router rather than a straight line.

``bookings``
    Who reserved the room and when, plus the lifecycle the engine mutates:
    ``active`` -> ``checked_in`` | ``ghost_released`` | ``reclaimed`` |
    ``completed``.

``occupancy_signals``
    **Headcount only.** No names, no device ids, no images, no cameras. Two
    sources: a QR check-in at the door and a simulated sensor feed. This is a
    hard product rule, not an implementation detail - it is why the table has
    exactly one numeric column.

``space_requests``
    A student asking for a room: how many seats, when, and whether they need
    step-free access. Only the *shape* of the requester is stored, never who.

``noshow_stats``
    Historical ``(organizer_type, weekday, hour)`` counts used for the
    Beta-smoothed no-show prior. This is the "prediction" - a smoothed
    historical rate, not a trained model.

All timestamps are timezone-aware. Booking windows are stored in UTC and the
engine compares them against the demo clock, never ``datetime.now()`` directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.database import Base, UTCDateTime

BOOKING_STATUSES: tuple[str, ...] = (
    "active",
    "checked_in",
    "ghost_released",
    "reclaimed",
    "completed",
    "cancelled",
)

ORGANIZER_TYPES: tuple[str, ...] = ("faculty", "club", "student_group", "admin")

OCCUPANCY_SOURCES: tuple[str, ...] = ("qr_checkin", "simulated_sensor")

REQUEST_STATUSES: tuple[str, ...] = (
    "open",
    "matched",
    "unfulfilled",
    "expired",
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    building: Mapped[str] = mapped_column(String(120), index=True)
    floor: Mapped[str] = mapped_column(String(32), default="1")
    capacity: Mapped[int] = mapped_column(Integer, default=0)
    #: Graph node this room is entered through. Reachability is measured from
    #: here, so a "step-free room" means "step-free *route to this node*".
    node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    is_step_free_access: Mapped[bool] = mapped_column(Boolean, default=True)
    has_accessible_features: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Estimated lighting + HVAC draw while the room is "in use". Used only for
    #: the energy *estimate* - there is no meter behind it.
    power_kw: Mapped[float] = mapped_column(Float, default=1.2)
    accessible_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow
    )

    node: Mapped["CampusNode | None"] = relationship(
        "CampusNode", foreign_keys=[node_id], viewonly=True
    )
    bookings: Mapped[list["Booking"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )

    @property
    def effective_power_kw(self) -> float:
        """Power while occupied. Empty-but-booked runs at the setback level."""
        return max(0.0, float(self.power_kw))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "building": self.building,
            "floor": self.floor,
            "capacity": self.capacity,
            "node_id": self.node_id,
            "is_step_free_access": self.is_step_free_access,
            "has_accessible_features": self.has_accessible_features,
            "power_kw": round(float(self.power_kw), 3),
            "accessible_notes": self.accessible_notes,
        }


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    organizer_type: Mapped[str] = mapped_column(String(24), index=True)
    #: Free-text organiser label is intentionally absent: we track the *class*
    #: of organiser (which drives the no-show prior), never a person.
    title: Mapped[str] = mapped_column(String(200), default="Room booking")
    start_ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    expected_attendees: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    release_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reclaimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    #: Snapshot of the decision that released (or declined to release) this
    #: booking, stored as JSON so the explainer drawer can replay it verbatim.
    decision_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Ground truth from the seed/simulator: did anybody actually turn up?
    simulated_will_show: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, index=True
    )

    room: Mapped[Room] = relationship(back_populates="bookings")
    signals: Mapped[list["OccupancySignal"]] = relationship(
        back_populates="booking", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_bookings_window", "start_ts", "end_ts", "status"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "organizer_type": self.organizer_type,
            "title": self.title,
            "start_ts": _iso(self.start_ts),
            "end_ts": _iso(self.end_ts),
            "expected_attendees": self.expected_attendees,
            "status": self.status,
            "release_reason": self.release_reason,
            "released_at": _iso(self.released_at),
            "reclaimed_at": _iso(self.reclaimed_at),
            "completed_at": _iso(self.completed_at),
            "simulated_will_show": self.simulated_will_show,
        }


class OccupancySignal(Base):
    """Headcount only. No identities, no images, no cameras.

    This is the privacy contract for Ghost Space: the system learns *how many*
    people are in a room, never *who*. There is deliberately no ``user_id``,
    ``device_id``, ``image_url`` or ``face`` column to leak.
    """

    __tablename__ = "occupancy_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("rooms.id", ondelete="CASCADE"), index=True
    )
    booking_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True, index=True
    )
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    headcount: Mapped[int] = mapped_column(Integer, default=0)
    source: Mapped[str] = mapped_column(String(24), default="simulated_sensor")
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    booking: Mapped[Booking | None] = relationship(back_populates="signals")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "room_id": self.room_id,
            "booking_id": self.booking_id,
            "ts": _iso(self.ts),
            "headcount": self.headcount,
            "source": self.source,
            "simulated": self.simulated,
        }


class SpaceRequest(Base):
    __tablename__ = "space_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    needs_step_free: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    capacity_needed: Mapped[int] = mapped_column(Integer, default=1)
    start_ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    end_ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    matched_room_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )
    #: Where the requester is standing, for the reachability check.
    origin_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    origin_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    #: Full ranked result + explanation, stored as JSON.
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, index=True
    )

    room: Mapped[Room | None] = relationship()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "needs_step_free": self.needs_step_free,
            "capacity_needed": self.capacity_needed,
            "start_ts": _iso(self.start_ts),
            "end_ts": _iso(self.end_ts),
            "status": self.status,
            "matched_room_id": self.matched_room_id,
            "origin_latitude": self.origin_latitude,
            "origin_longitude": self.origin_longitude,
            "origin_label": self.origin_label,
            "created_at": _iso(self.created_at),
        }


class NoShowStat(Base):
    """Smoothed historical no-show rate per (organizer_type, weekday, hour).

    This is the "prediction model": a Beta-smoothed rate
    ``(noshow_count + alpha) / (bookings_count + alpha + beta)``. No ML
    dependency, fully explainable, and it degrades gracefully to the
    organiser-type average when a cell is thin.
    """

    __tablename__ = "noshow_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    organizer_type: Mapped[str] = mapped_column(String(24), index=True)
    weekday: Mapped[int] = mapped_column(Integer, index=True)  # 0=Mon .. 6=Sun
    hour: Mapped[int] = mapped_column(Integer, index=True)  # 0..23
    bookings_count: Mapped[int] = mapped_column(Integer, default=0)
    noshow_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint(
            "organizer_type", "weekday", "hour", name="uq_noshow_cell"
        ),
    )

    def smoothed_rate(self, *, alpha: float | None = None, beta: float | None = None) -> float:
        """Beta-smoothed no-show rate in [0, 1]."""
        a = settings.ghost_beta_alpha if alpha is None else alpha
        b = settings.ghost_beta_beta if beta is None else beta
        return (self.noshow_count + a) / (self.bookings_count + a + b)

    def to_dict(self) -> dict[str, Any]:
        return {
            "organizer_type": self.organizer_type,
            "weekday": self.weekday,
            "hour": self.hour,
            "bookings_count": self.bookings_count,
            "noshow_count": self.noshow_count,
            "smoothed_noshow_rate": round(self.smoothed_rate(), 4),
        }


__all__ = [
    "BOOKING_STATUSES",
    "Booking",
    "NoShowStat",
    "OCCUPANCY_SOURCES",
    "ORGANIZER_TYPES",
    "OccupancySignal",
    "REQUEST_STATUSES",
    "Room",
    "SpaceRequest",
]