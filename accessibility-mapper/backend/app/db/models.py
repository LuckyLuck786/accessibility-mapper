"""Phase 1 - spatial data model.

Portable across SQLite / PostgreSQL / PostGIS:
  * ``latitude`` / ``longitude`` Float columns are the single source of truth.
  * ``Node.to_geojson()`` / ``Edge.to_geojson()`` / ``Barrier.to_geojson()``
    emit RFC 7946 features that Leaflet consumes directly.
  * When PostGIS is enabled the bootstrap script adds ``geography`` mirrors and
    GiST indexes (see ``app.core.database.POSTGIS_DDL``) for indexed
    ``ST_DWithin`` proximity queries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.constants import (
    CATEGORY_COLORS,
    CATEGORY_LABELS,
    CATEGORY_SEVERITY,
    CATEGORY_TTL_HOURS,
    SEVERITY_COLORS,
    STEP_FREE_BLOCKING,
)
from app.core.database import Base, UTCDateTime


def utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20), default="student")
    password_hash: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "full_name": self.full_name,
            "role": self.role,
        }


# ---------------------------------------------------------------------------
# Serverless infrastructure tables
# ---------------------------------------------------------------------------
class AppState(Base):
    """Tiny key/value store for cross-instance coordination.

    The important row is ``graph_version``: every barrier or edge mutation
    bumps it, and every request compares its cached graph against it so a warm
    function instance never serves a stale routing graph.
    """

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow
    )


class MediaObject(Base):
    """A redacted JPEG stored as ``bytea``.

    Serverless filesystems are read-only, so images live in the database and
    are streamed back out by ``GET /api/v1/media/{id}``. Only ever holds the
    *redacted* bytes - the original upload is discarded in the same request.
    """

    __tablename__ = "media_objects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), default="barrier_photo")
    content_type: Mapped[str] = mapped_column(String(48), default="image/jpeg")
    data: Mapped[bytes] = mapped_column(LargeBinary)
    thumbnail_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    faces_redacted: Mapped[int] = mapped_column(Integer, default=0)
    plates_redacted: Mapped[int] = mapped_column(Integer, default=0)
    privacy_engine: Mapped[str] = mapped_column(String(32), default="opencv-haar")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, index=True
    )


class ReportCounter(Base):
    """Per-client report quota, enforced in the database (no Redis needed)."""

    __tablename__ = "report_counters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_key: Mapped[str] = mapped_column(String(96), index=True)
    window_start: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    window_kind: Mapped[str] = mapped_column(String(8), default="hour")
    count: Mapped[int] = mapped_column(BigInteger, default=0)

    __table_args__ = (
        UniqueConstraint(
            "client_key", "window_kind", "window_start", name="uq_report_counter_window"
        ),
    )


# ---------------------------------------------------------------------------
# Phase 1.1 - Nodes: buildings, entrances, lifts, doors, path intersections
# ---------------------------------------------------------------------------
class CampusNode(Base):
    __tablename__ = "nodes"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(24), default="intersection", index=True)
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    has_elevator: Mapped[bool] = mapped_column(Boolean, default=False)
    is_entrance: Mapped[bool] = mapped_column(Boolean, default=False)
    is_step_free: Mapped[bool] = mapped_column(Boolean, default=True)
    building_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    accessible_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    campus_zone: Mapped[str | None] = mapped_column(String(40), nullable=True)

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            },
            "properties": {
                "id": self.id,
                "name": self.name,
                "kind": self.kind,
                "has_elevator": self.has_elevator,
                "is_entrance": self.is_entrance,
                "is_step_free": self.is_step_free,
                "building_code": self.building_code,
                "accessible_notes": self.accessible_notes,
                "campus_zone": self.campus_zone,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return self.to_geojson()["properties"] | {
            "latitude": self.latitude,
            "longitude": self.longitude,
        }


# ---------------------------------------------------------------------------
# Phase 1.2 - Edges: footpaths, corridors, stairs, ramps
# ---------------------------------------------------------------------------
class CampusEdge(Base):
    __tablename__ = "edges"

    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), default="Pathway")
    kind: Mapped[str] = mapped_column(String(20), default="footpath", index=True)
    source_node_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    target_node_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    distance_m: Mapped[float] = mapped_column(Float, default=0.0)
    is_step_free: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    width_m: Mapped[float] = mapped_column(Float, default=2.0)
    incline_pct: Mapped[float] = mapped_column(Float, default=0.0)
    active_barriers_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    traffic_weight: Mapped[float] = mapped_column(Float, default=1.0)
    #: Materialised dynamic weight - recomputed by the graph service whenever a
    #: barrier changes so the DB view and the in-memory graph never diverge.
    #: Always finite: ``distance_m * (1 + multiplier * active_barriers_count)``.
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    #: True when a hard-blocking barrier (blocked ramp / broken lift / narrow
    #: path) severs this edge for step-free travel. Mirrors the router's
    #: notion of "impassable in accessible mode" so the map can render it.
    step_free_blocked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    #: Exit-only doors / one-way turnstiles would set this; campus footpaths
    #: default to bidirectional (the router mirrors them in memory).
    oneway: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    source_node: Mapped[CampusNode] = relationship(foreign_keys=[source_node_id])
    target_node: Mapped[CampusNode] = relationship(foreign_keys=[target_node_id])
    barriers: Mapped[list["Barrier"]] = relationship(back_populates="edge")

    __table_args__ = (
        UniqueConstraint("source_node_id", "target_node_id", "kind", name="uq_edge_triple"),
        Index("ix_edges_step_free_kind", "is_step_free", "kind"),
    )

    def coordinates(self) -> list[list[float]]:
        return [
            [self.source_node.longitude, self.source_node.latitude],
            [self.target_node.longitude, self.target_node.latitude],
        ]

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": self.coordinates()},
            "properties": {
                "id": self.id,
                "name": self.name,
                "kind": self.kind,
                "source_node_id": self.source_node_id,
                "target_node_id": self.target_node_id,
                "distance_m": round(self.distance_m, 2),
                "is_step_free": self.is_step_free,
                "width_m": self.width_m,
                "incline_pct": self.incline_pct,
                "active_barriers_count": self.active_barriers_count,
                "weight": round(self.weight, 3),
                "step_free_blocked": bool(self.step_free_blocked),
                "traffic_weight": self.traffic_weight,
            },
        }


# ---------------------------------------------------------------------------
# Phase 1.3 - Barriers
# ---------------------------------------------------------------------------
class Barrier(Base):
    __tablename__ = "barriers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="unverified", index=True)
    severity: Mapped[int] = mapped_column(Integer, default=3)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: MediaObjects.id of the redacted JPEG (not a filesystem path - the
    #: serverless bundle has no writable media directory).
    image_path: Mapped[str | None] = mapped_column(String(64), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(64), nullable=True)
    redacted_faces: Mapped[int] = mapped_column(Integer, default=0)
    redacted_plates: Mapped[int] = mapped_column(Integer, default=0)
    detection_source: Mapped[str] = mapped_column(String(24), default="citizen_manual")
    detection_boxes: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob
    edge_id: Mapped[str | None] = mapped_column(
        String(60), ForeignKey("edges.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reporter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reporter_label: Mapped[str] = mapped_column(String(80), default="anonymous")
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    ticket_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow
    )
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)

    edge: Mapped[CampusEdge | None] = relationship(back_populates="barriers")
    confirmations_log: Mapped[list["BarrierConfirmation"]] = relationship(
        back_populates="barrier", cascade="all, delete-orphan"
    )
    events: Mapped[list["BarrierEvent"]] = relationship(
        back_populates="barrier", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_barriers_status_category", "status", "category"),
        Index("ix_barriers_bbox", "latitude", "longitude"),
    )

    # --- behaviour --------------------------------------------------------
    @property
    def is_active(self) -> bool:
        if self.status in ("resolved", "expired"):
            return False
        if self.expires_at and self._aware(self.expires_at) < utcnow():
            return False
        return True

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    @property
    def is_hard_block(self) -> bool:
        """True when the barrier makes step-free travel physically impossible."""
        return self.category in STEP_FREE_BLOCKING

    @property
    def label(self) -> str:
        return CATEGORY_LABELS.get(self.category, self.category.replace("_", " ").title())

    @property
    def color(self) -> str:
        return CATEGORY_COLORS.get(self.category, SEVERITY_COLORS.get(self.severity, "#64748b"))

    @property
    def age_hours(self) -> float:
        return max(0.0, (utcnow() - self._aware(self.created_at)).total_seconds() / 3600.0)

    @property
    def resolution_hours(self) -> float | None:
        if not self.resolved_at:
            return None
        delta = self._aware(self.resolved_at) - self._aware(self.created_at)
        return round(max(0.0, delta.total_seconds() / 3600.0), 2)

    @staticmethod
    def default_expiry(category: str, *, from_time: datetime | None = None) -> datetime:
        base = from_time or utcnow()
        hours = CATEGORY_TTL_HOURS.get(category, settings.barrier_ttl_hours)
        return base + timedelta(hours=hours)

    def to_dict(self, *, include_image: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "category": self.category,
            "label": self.label,
            "severity": CATEGORY_SEVERITY.get(self.category, self.severity),
            "color": self.color,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "confidence": round(self.confidence, 3),
            "status": self.status,
            "description": self.description,
            "redacted_faces": self.redacted_faces,
            "redacted_plates": self.redacted_plates,
            "detection_source": self.detection_source,
            "edge_id": self.edge_id,
            "reporter_label": self.reporter_label,
            "confirmations": self.confirmations,
            "ticket_id": self.ticket_id,
            "is_active": self.is_active,
            "is_hard_block": self.is_hard_block,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "verified_at": _iso(self.verified_at),
            "resolved_at": _iso(self.resolved_at),
            "expires_at": _iso(self.expires_at),
            "age_hours": round(self.age_hours, 2),
            "resolution_hours": self.resolution_hours,
        }
        if include_image and self.image_path:
            data["image_url"] = f"{settings.media_url_prefix}/{self.image_path}"
        return data

    def to_geojson(self) -> dict[str, Any]:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude],
            },
            "properties": self.to_dict(),
        }


class BarrierConfirmation(Base):
    """One row per citizen confirmation - powers the auto-verify rule."""

    __tablename__ = "barrier_confirmations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barrier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("barriers.id", ondelete="CASCADE"), index=True
    )
    reporter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reporter_label: Mapped[str] = mapped_column(String(80), default="anonymous")
    distance_m: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    barrier: Mapped[Barrier] = relationship(back_populates="confirmations_log")


class BarrierEvent(Base):
    """Append-only status history: audit trail + resolution-time analytics."""

    __tablename__ = "barrier_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    barrier_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("barriers.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(80), default="system")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, index=True
    )

    barrier: Mapped[Barrier] = relationship(back_populates="events")


# ---------------------------------------------------------------------------
# Phase 6 - Maintenance tickets
# ---------------------------------------------------------------------------
class MaintenanceTicket(Base):
    __tablename__ = "maintenance_tickets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    barrier_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("barriers.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(12), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    assigned_team: Mapped[str] = mapped_column(String(80), default="unassigned")
    impact_score: Mapped[float] = mapped_column(Float, default=0.0)
    edge_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    sla_hours: Mapped[int] = mapped_column(Integer, default=72)
    location_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    barrier: Mapped[Barrier | None] = relationship()

    @property
    def age_hours(self) -> float:
        return max(0.0, (utcnow() - Barrier._aware(self.created_at)).total_seconds() / 3600.0)

    @property
    def breach_risk(self) -> float:
        """0..1 - how close this ticket is to breaching its SLA."""
        if self.status == "resolved" or self.sla_hours <= 0:
            return 0.0
        return min(1.0, round(self.age_hours / self.sla_hours, 3))

    def to_dict(self) -> dict[str, Any]:
        barrier = self.barrier
        return {
            "id": self.id,
            "code": self.code,
            "barrier_id": self.barrier_id,
            "title": self.title,
            "detail": self.detail,
            "priority": self.priority,
            "status": self.status,
            "assigned_team": self.assigned_team,
            "impact_score": round(self.impact_score, 2),
            "edge_id": self.edge_id,
            "sla_hours": self.sla_hours,
            "location_name": self.location_name,
            "created_at": _iso(self.created_at),
            "updated_at": _iso(self.updated_at),
            "resolved_at": _iso(self.resolved_at),
            "age_hours": round(self.age_hours, 2),
            "breach_risk": self.breach_risk,
            "latitude": barrier.latitude if barrier else None,
            "longitude": barrier.longitude if barrier else None,
            "category": barrier.category if barrier else None,
            "category_label": barrier.label if barrier else None,
            "color": barrier.color if barrier else "#64748b",
        }
