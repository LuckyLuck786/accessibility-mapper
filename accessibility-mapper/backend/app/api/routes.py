"""Routing endpoints: step-free A* planning, presets, campus network layer."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import DbSession
from app.db.seed import campus_bounds, preset_destinations
from app.schemas.campus import CampusNetworkOut, GraphStatsOut, PresetsOut
from app.schemas.routing import RoutePlanRequest, RoutePlanResponse
from app.services import barrier_service
from app.services.graph_service import graph_service

router = APIRouter(tags=["routing"])


@router.post(
    "/routes/plan",
    response_model=RoutePlanResponse,
    summary="Plan the best barrier-aware campus route",
    description="""
Runs A* over the live campus graph. Edge cost is
`distance x step_free_penalty x (1 + 10 x active_barriers)`.

With `wheelchair_accessible=true`, stair-only segments **and** edges carrying a
hard-blocking barrier (blocked ramp, broken lift, narrow path) become
impassable. If that severs the only step-free chain, the response comes back
`degraded=true` with a least-bad route and critical warnings instead of a bare
error, so the user always gets actionable guidance.
""",
)
def plan_route(payload: RoutePlanRequest, db: DbSession) -> RoutePlanResponse:
    result = graph_service.find_accessible_route(
        db,
        payload.start_lat,
        payload.start_lng,
        payload.end_lat,
        payload.end_lng,
        wheelchair_accessible=payload.wheelchair_accessible,
        avoid_construction=payload.avoid_construction,
    )
    if not result.get("found") and not result.get("warnings"):
        result.setdefault("warnings", [])
    return RoutePlanResponse.model_validate(result)


@router.get(
    "/routes/presets",
    response_model=PresetsOut,
    summary="Quick-pick campus destinations for the sidebar",
)
def presets(db: DbSession) -> PresetsOut:
    return PresetsOut(presets=preset_destinations(db), bounds=campus_bounds(db))


@router.get(
    "/campus/network",
    response_model=CampusNetworkOut,
    summary="Full walkway network + nodes as GeoJSON",
)
def campus_network(db: DbSession, include_nodes: bool = Query(default=True)) -> CampusNetworkOut:
    payload = barrier_service.campus_network_geojson(db, include_nodes=include_nodes)
    return CampusNetworkOut.model_validate(payload)


@router.get(
    "/campus/graph/stats",
    response_model=GraphStatsOut,
    summary="Graph diagnostics (step-free coverage, components)",
)
def graph_stats(db: DbSession) -> GraphStatsOut:
    return GraphStatsOut.model_validate(graph_service.stats(db))


@router.get(
    "/campus/nodes/{node_id}",
    summary="Node detail including every incident edge and barrier",
)
def node_detail(node_id: str, db: DbSession) -> dict:
    from sqlalchemy import select

    from app.db.models import Barrier, CampusEdge, CampusNode

    node = db.get(CampusNode, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found")
    edges = list(
        db.scalars(
            select(CampusEdge).where(
                (CampusEdge.source_node_id == node_id)
                | (CampusEdge.target_node_id == node_id)
            )
        )
    )
    edge_ids = [edge.id for edge in edges]
    barriers = (
        list(
            db.scalars(
                select(Barrier).where(Barrier.edge_id.in_(edge_ids))
            )
        )
        if edge_ids
        else []
    )
    return {
        "node": node.to_dict(),
        "edges": [edge.to_geojson()["properties"] for edge in edges],
        "barriers": [barrier.to_dict(include_image=False) for barrier in barriers if barrier.is_active],
        "step_free_degree": sum(1 for edge in edges if edge.is_step_free),
    }


@router.get(
    "/campus/accessibility-audit",
    summary="Which destinations are currently unreachable step-free?",
    description=(
        "Walks the step-free subgraph from every entrance and reports the "
        "facilities that a wheelchair user cannot currently reach because of a "
        "hard-blocking barrier. This is the report the accessibility office "
        "would actually run."
    ),
)
def accessibility_audit(db: DbSession) -> dict:
    import networkx as nx
    from sqlalchemy import select

    from app.db.models import CampusNode

    graph_service.ensure_loaded(db)
    graph = graph_service.graph

    hard_blocks = {
        barrier.edge_id
        for barrier in barrier_service.active_barriers(db)
        if barrier.is_hard_block and barrier.edge_id
    }

    step_free = nx.MultiDiGraph()
    # A doorway you can only enter by climbing steps is not an accessible door:
    # corridors hanging off it must be excluded too, otherwise the audit happily
    # "reaches" a building through a stair landing.
    stepped_entries = {
        node_id
        for node_id, attrs in graph.nodes(data=True)
        if attrs.get("kind") == "entrance" and not attrs.get("is_step_free", True)
    }
    for u, v, key, data in graph.edges(keys=True, data=True):
        if not data.get("is_step_free") or key in hard_blocks:
            continue
        if u in stepped_entries or v in stepped_entries:
            continue
        step_free.add_edge(u, v, key=key)
    for node_id in graph.nodes:
        step_free.add_node(node_id, **graph.nodes[node_id])

    facilities = [
        node
        for node in db.scalars(select(CampusNode))
        if node.kind in ("building", "facility")
    ]
    # Seed the walk from where a traveller genuinely starts: street-level
    # junctions. Seeding from "any node with an edge" (or from a door that sits
    # behind the very edge we just severed) would let an isolated interior
    # pocket vouch for its own reachability.
    seeds = [
        node_id
        for node_id, attrs in graph.nodes(data=True)
        if attrs.get("kind") == "intersection"
    ]
    reachable: set[str] = set()
    for source in seeds:
        if source not in step_free:
            continue
        reachable.add(source)
        reachable.update(nx.descendants(step_free, source))

    unreachable = [
        {
            "id": node.id,
            "name": node.name,
            "kind": node.kind,
            "latitude": node.latitude,
            "longitude": node.longitude,
            "campus_zone": node.campus_zone,
        }
        for node in facilities
        if node.id not in reachable
    ]
    return {
        "step_free_graph": {
            "nodes": step_free.number_of_nodes(),
            "edges": step_free.number_of_edges(),
            "components": nx.number_weakly_connected_components(step_free)
            if step_free.number_of_nodes()
            else 0,
        },
        "blocked_edges": sorted(hard_blocks),
        "stepped_entries": sorted(stepped_entries),
        "unreachable_facilities": unreachable,
        "unreachable_count": len(unreachable),
        "verdict": (
            "All campus facilities are step-free reachable."
            if not unreachable
            else f"{len(unreachable)} facility/facilities need an accessibility intervention."
        ),
    }
