"""Route planning contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RoutePlanRequest(BaseModel):
    start_lat: float = Field(..., ge=-90, le=90, examples=[47.65564])
    start_lng: float = Field(..., ge=-180, le=180, examples=[-122.30807])
    end_lat: float = Field(..., ge=-90, le=90, examples=[47.65622])
    end_lng: float = Field(..., ge=-180, le=180, examples=[-122.30424])
    wheelchair_accessible: bool = Field(
        default=True,
        description="When true, stair-only and hard-blocked segments are removed from the search space.",
    )
    start_label: str | None = Field(default=None, max_length=120)
    end_label: str | None = Field(default=None, max_length=120)
    prefer_covered: bool = False
    avoid_construction: bool = False
    max_incline_pct: float | None = Field(default=None, ge=0, le=30)


class RouteStepOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: int
    action: str
    instruction: str
    distance_m: float
    cumulative_m: float
    compass: str | None = None
    kind: str | None = None
    is_step_free: bool = True
    cautions: list[dict[str, Any]] = Field(default_factory=list)
    to_node: str | None = None


class RouteWarningOut(BaseModel):
    code: str
    message: str
    severity: Literal["info", "medium", "high", "critical"] = "info"
    barrier_id: int | None = None
    distance_m: float | None = None


class RouteSegmentOut(BaseModel):
    edge_id: str
    name: str | None = None
    kind: str | None = None
    distance_m: float
    is_step_free: bool = True
    width_m: float | None = None
    incline_pct: float | None = None
    active_barriers_count: int = 0
    weight: float | None = None


class RouteEndpointOut(BaseModel):
    requested: dict[str, float] | None = None
    node_id: str | None = None
    snap_distance_m: float = 0.0


class RouteSummaryOut(BaseModel):
    accessibility_grade: Literal[
        "step_free", "step_free_with_caution", "not_step_free", "standard"
    ]
    max_incline_pct: float = 0.0
    min_width_m: float | None = None
    step_free_segments: int = 0
    total_segments: int = 0
    barrier_count: int = 0


class RoutePlanResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    found: bool
    algorithm: str | None = None
    wheelchair_accessible: bool = False
    degraded: bool = False
    distance_m: float = 0.0
    distance_text: str | None = None
    duration_s: float = 0.0
    duration_min: float = 0.0
    duration_text: str | None = None
    speed_mps: float | None = None
    geojson: dict[str, Any] | None = None
    coordinates: list[list[float]] = Field(default_factory=list)
    steps: list[RouteStepOut] = Field(default_factory=list)
    segments: list[RouteSegmentOut] = Field(default_factory=list)
    warnings: list[RouteWarningOut] = Field(default_factory=list)
    barriers_on_route: list[dict[str, Any]] = Field(default_factory=list)
    node_path: list[str] = Field(default_factory=list)
    edge_path: list[str] = Field(default_factory=list)
    summary: RouteSummaryOut | None = None
    start: RouteEndpointOut | None = None
    end: RouteEndpointOut | None = None
    reason: str | None = None
    message: str | None = None
    blocked_edges: list[str] = Field(default_factory=list)
