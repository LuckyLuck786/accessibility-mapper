"""Campus network + graph diagnostics contracts."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PresetOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    node_id: str
    label: str
    category: str | None = None
    icon: str | None = None
    note: str | None = None
    name: str | None = None
    latitude: float
    longitude: float
    has_elevator: bool = False
    is_step_free: bool = True
    campus_zone: str | None = None


class PresetsOut(BaseModel):
    presets: list[PresetOut]
    bounds: dict[str, float] | None = None


class CampusNetworkOut(BaseModel):
    type: str = "FeatureCollection"
    features: list[dict[str, Any]]
    meta: dict[str, Any] = Field(default_factory=dict)


class GraphStatsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    nodes: int
    edges: int
    directed_arcs: int = 0
    step_free_edges: int
    stairs_edges: int
    step_free_components: int
    isolated_step_free_zones: int
    buildings: int
    lift_nodes: int = 0
    nodes_with_elevator: int = 0
    entrances: int
    algorithm: str


class SystemStatusOut(BaseModel):
    app: str
    version: str
    environment: str
    database: str
    graph: dict[str, Any]
    cv: dict[str, Any]
    routing: dict[str, Any]
    policies: dict[str, Any]
