"""Administrator dashboard contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ResolveRequest(BaseModel):
    resolution_note: str | None = Field(
        default=None,
        max_length=500,
        examples=["Pallets moved to the loading bay; ramp cleared."],
    )
    actor: str | None = Field(default=None, max_length=80)
    reopen_ticket: bool = False


class TicketStatusRequest(BaseModel):
    status: Literal["open", "in_progress", "resolved"]
    note: str | None = Field(default=None, max_length=400)
    assigned_team: str | None = Field(default=None, max_length=80)


class TicketOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    code: str
    barrier_id: int | None
    title: str
    detail: str | None = None
    priority: Literal["low", "medium", "high", "critical"]
    status: Literal["open", "in_progress", "resolved"]
    assigned_team: str
    impact_score: float
    edge_id: str | None = None
    sla_hours: int
    location_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    resolved_at: str | None = None
    age_hours: float = 0.0
    breach_risk: float = 0.0
    latitude: float | None = None
    longitude: float | None = None
    category: str | None = None
    category_label: str | None = None
    color: str | None = None


class AnalyticsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    generated_at: str
    kpis: dict[str, Any]
    category_breakdown: list[dict[str, Any]] = Field(default_factory=list)
    heatmap: list[dict[str, Any]] = Field(default_factory=list)
    hotspot_zones: list[dict[str, Any]] = Field(default_factory=list)
    resolution_trend: list[dict[str, Any]] = Field(default_factory=list)
    tickets: dict[str, Any] = Field(default_factory=dict)
    routing_health: dict[str, Any] = Field(default_factory=dict)
    recent_reports: list[dict[str, Any]] = Field(default_factory=list)
    status_mix: dict[str, int] = Field(default_factory=dict)


class SweepOut(BaseModel):
    expired: int
    message: str


class ActionOut(BaseModel):
    action: str
    message: str
    barrier: dict[str, Any] | None = None
    ticket: dict[str, Any] | None = None
    graph: dict[str, Any] | None = None
