"""Phase 2 - self-updating campus accessibility graph + step-free A* routing.

Architecture
------------
The campus is modelled as a NetworkX ``MultiDiGraph`` held in process memory and
kept in sync with the ``nodes`` / ``edges`` tables. A MultiDiGraph (not a plain
DiGraph) is used because parallel edges are *the* normal case on a campus: a
stair flight and a ramp almost always connect the same pair of nodes, and the
router has to choose between them.

Dynamic weight function
-----------------------
    weight = distance_m * step_free_penalty * (1 + barrier_multiplier * active_barriers)

``step_free_penalty`` becomes infinite for stairs/kerbs when
``accessible_mode`` is on, so the A* search can never return a route a
wheelchair user cannot physically take. Edges carrying a *hard-blocking*
barrier (blocked ramp, broken lift, narrow path) are also severed, and that
state is materialised on the edge row as ``step_free_blocked`` so the database,
the map and the router can never disagree.

Why the recompute is global
---------------------------
Every barrier mutation refreshes the whole graph (~57 edges on the seed campus,
a few hundred on a real one). Doing targeted edge patches invites exactly the
class of bug this file used to have - a stale object that silently kept a
severed edge open. At campus scale a full pass costs well under a millisecond,
so correctness wins; :meth:`GraphService.sync_barrier_penalties` still takes the
touched edge ids so callers get a precise change report (and so an incremental
implementation can be dropped in later without touching call sites).

The graph deliberately stores **plain attribute dictionaries**, never ORM
instances: ORM objects are bound to the session that loaded them, and caching
them across requests makes writes silently no-ops.
"""

from __future__ import annotations

import logging
import math
import threading
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.constants import CATEGORY_LABELS, CATEGORY_SEVERITY
from app.core.geo import (
    bearing_deg,
    compass_label,
    haversine_m,
    polyline_length_m,
    turn_delta_deg,
)
from app.db.models import Barrier, CampusEdge, CampusNode

logger = logging.getLogger("abm.graph")

ACTIVE_BARRIER_STATUSES = ("unverified", "verified", "in_progress")

#: Soft penalty applied to a severed edge during degraded (least-bad) routing.
_DEGRADED_BLOCK_PENALTY = 1_000.0

TURN_LEFT = "Turn left"
TURN_RIGHT = "Turn right"
TURN_SLIGHT_LEFT = "Bear left"
TURN_SLIGHT_RIGHT = "Bear right"
CONTINUE = "Continue straight"
ARRIVE = "Arrive at destination"

#: How far off-route a barrier can be before we stop warning about it.
ALERT_RADIUS_M = 60.0


def _local_xy(lat: float, lng: float, ref_lat: float, ref_lng: float) -> tuple[float, float]:
    """Equirectangular projection to metres around a reference point."""
    x = math.radians(lng - ref_lng) * math.cos(math.radians(ref_lat)) * 6_371_008.8
    y = math.radians(lat - ref_lat) * 6_371_008.8
    return x, y


def _project_point_to_segment(
    lat: float,
    lng: float,
    a_lat: float,
    a_lng: float,
    b_lat: float,
    b_lng: float,
) -> tuple[float, float, float, float]:
    """Project a point onto a segment.

    Returns ``(perp_distance_m, t, proj_lat, proj_lng)`` where ``t`` is the
    normalised position along the segment.
    """
    px, py = _local_xy(lat, lng, a_lat, a_lng)
    bx, by = _local_xy(b_lat, b_lng, a_lat, a_lng)
    seg_len_sq = bx * bx + by * by
    if seg_len_sq == 0:
        return haversine_m(lat, lng, a_lat, a_lng), 0.0, a_lat, a_lng
    t = max(0.0, min(1.0, (px * bx + py * by) / seg_len_sq))
    proj_lat = a_lat + t * (b_lat - a_lat)
    proj_lng = a_lng + t * (b_lng - a_lng)
    return haversine_m(lat, lng, proj_lat, proj_lng), t, proj_lat, proj_lng


class GraphService:
    """Thread-safe singleton owning the in-memory campus graph."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._graph: nx.MultiDiGraph | None = None
        self._node_attrs: dict[str, dict[str, Any]] = {}
        self._edge_attrs: dict[str, dict[str, Any]] = {}
        self._load_count = 0
        self._last_loaded_at: datetime | None = None
        self._last_recompute_at: datetime | None = None
        #: The ``app_state.graph_version`` this in-memory graph was built from.
        #: Every mutation bumps the shared row; :meth:`ensure_fresh` compares the
        #: two and rebuilds only when they diverge. This is what makes a warm
        #: serverless instance safe to reuse.
        self._graph_version: int | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    @property
    def graph(self) -> nx.MultiDiGraph:
        if self._graph is None:
            raise RuntimeError("Graph not loaded - call ensure_loaded(db) first")
        return self._graph

    @property
    def is_loaded(self) -> bool:
        return self._graph is not None

    @property
    def graph_version(self) -> int | None:
        """Version of the cached graph, or ``None`` when nothing is loaded."""
        return self._graph_version

    def invalidate(self) -> None:
        """Force a rebuild on next access (network topology changed)."""
        with self._lock:
            self._graph = None
            self._node_attrs = {}
            self._edge_attrs = {}
            self._graph_version = None

    def ensure_loaded(self, db: Session) -> nx.MultiDiGraph:
        with self._lock:
            if self._graph is None:
                self.load(db)
            return self._graph

    def ensure_fresh(self, db: Session) -> nx.MultiDiGraph:
        """Load, or reload only when the shared ``graph_version`` has moved.

        Called by the request dependency rather than by every endpoint, so a
        cold instance rebuilds on its first request and a warm instance picks up
        a barrier change made by *another* instance without any shared memory.
        """
        from app.core.database import read_graph_version

        with self._lock:
            current = read_graph_version(db)
            if self._graph is None or self._graph_version != current:
                self._graph = None
                self._graph_version = current
                self.load(db)
            return self._graph

    def mark_dirty(self, db: Session) -> int:
        """Bump the shared version so every instance reloads on its next request.

        Called by any mutation (barrier status, edge weights, topology). The
        next ``ensure_fresh`` in *any* instance sees the new number and rebuilds.
        """
        from app.core.database import bump_graph_version

        with self._lock:
            self._graph_version = None
            self._graph = None
            self._node_attrs = {}
            self._edge_attrs = {}
        return bump_graph_version(db)

    def load(self, db: Session) -> nx.MultiDiGraph:
        """(Re)build the graph from the database, caching plain dicts only."""
        with self._lock:
            graph = nx.MultiDiGraph()
            nodes = {n.id: n for n in db.scalars(select(CampusNode))}
            edges = {e.id: e for e in db.scalars(select(CampusEdge))}

            node_attrs: dict[str, dict[str, Any]] = {}
            for node in nodes.values():
                attrs = {
                    "id": node.id,
                    "name": node.name,
                    "kind": node.kind,
                    "latitude": float(node.latitude),
                    "longitude": float(node.longitude),
                    "has_elevator": bool(node.has_elevator),
                    "is_entrance": bool(node.is_entrance),
                    "is_step_free": bool(node.is_step_free),
                    "building_code": node.building_code,
                    "campus_zone": node.campus_zone,
                    "accessible_notes": node.accessible_notes,
                }
                graph.add_node(node.id, **attrs)
                node_attrs[node.id] = attrs

            edge_attrs: dict[str, dict[str, Any]] = {}
            orphans = 0
            for edge in edges.values():
                if edge.source_node_id not in nodes or edge.target_node_id not in nodes:
                    orphans += 1
                    continue
                attrs = {
                    "edge_id": edge.id,
                    "id": edge.id,
                    "name": edge.name,
                    "kind": edge.kind,
                    "source_node_id": edge.source_node_id,
                    "target_node_id": edge.target_node_id,
                    "distance_m": float(edge.distance_m),
                    "is_step_free": bool(edge.is_step_free),
                    "width_m": float(edge.width_m),
                    "incline_pct": float(edge.incline_pct),
                    "active_barriers_count": int(edge.active_barriers_count),
                    "hard_blocks": 1 if edge.step_free_blocked else 0,
                    "step_free_blocked": bool(edge.step_free_blocked),
                    "traffic_weight": float(edge.traffic_weight),
                    "weight": float(edge.weight or edge.distance_m),
                    "oneway": False,
                }
                graph.add_edge(edge.source_node_id, edge.target_node_id, key=edge.id, **attrs)
                edge_attrs[edge.id] = attrs
                if not edge.oneway:
                    # A campus footpath is walkable in both directions. Modelling
                    # it as one row (with a mirrored graph edge) keeps barrier
                    # penalties and ticket impact attached to a single segment
                    # instead of duplicating rows per direction.
                    reverse = dict(attrs)
                    reverse["oneway"] = False
                    graph.add_edge(edge.target_node_id, edge.source_node_id, key=edge.id, **reverse)

            self._graph = graph
            self._node_attrs = node_attrs
            self._edge_attrs = edge_attrs
            if self._graph_version is None:
                from app.core.database import read_graph_version

                self._graph_version = read_graph_version(db)
            self._load_count += 1
            self._last_loaded_at = datetime.now(UTC)
            if orphans:
                logger.warning("skipped %s edges with missing endpoints", orphans)
            logger.info(
                "campus graph loaded: %s nodes / %s edges",
                graph.number_of_nodes(),
                graph.number_of_edges(),
            )
            return graph

    # ------------------------------------------------------------------
    # Weighting
    # ------------------------------------------------------------------
    def compute_edge_weight(
        self, attrs: dict[str, Any], *, accessible_mode: bool, hard_blocks: int = 0
    ) -> float:
        """Apply the documented dynamic weight formula to one edge."""
        distance = float(attrs.get("distance_m") or 0.0)
        step_free = bool(attrs.get("is_step_free", True))
        barriers = int(attrs.get("active_barriers_count") or 0)

        if accessible_mode:
            if not step_free:
                return math.inf
            if hard_blocks:
                # e.g. a blocked ramp or a broken lift: the step-free chain is
                # physically severed on this segment.
                return math.inf
            penalty = 1.0
        else:
            penalty = settings.stair_penalty_multiplier if not step_free else 1.0
            if hard_blocks:
                penalty *= _DEGRADED_BLOCK_PENALTY

        weight = distance * penalty * (1.0 + settings.barrier_weight_multiplier * barriers)
        return weight if math.isfinite(weight) else math.inf

    def _live_barrier_stats(self, db: Session) -> dict[str, tuple[int, int]]:
        """``edge_id -> (active_barriers, hard_blocks)`` for every edge.

        One query for the whole network; ``is_active`` (expiry-aware) is applied
        in Python because SQLite has no ``now()``-based predicate portability.
        """
        db.flush()  # make pending status changes visible to the SELECT
        rows = db.scalars(
            select(Barrier).where(
                Barrier.edge_id.is_not(None),
                Barrier.status.in_(ACTIVE_BARRIER_STATUSES),
            )
        )
        stats: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for barrier in rows:
            if not barrier.is_active or not barrier.edge_id:
                continue
            stats[barrier.edge_id][0] += 1
            if barrier.is_hard_block:
                stats[barrier.edge_id][1] += 1
        return {edge_id: (counts[0], counts[1]) for edge_id, counts in stats.items()}

    def recompute_weights(self, db: Session) -> dict[str, Any]:
        """Rebuild the graph and re-materialise every dynamic edge weight.

        Bumps the shared ``graph_version`` because this always follows a
        mutation, so every other instance must reload before routing again.
        """
        from app.core.database import bump_graph_version

        with self._lock:
            self.load(db)
            stats = self._live_barrier_stats(db)
            blocked: list[str] = []
            penalised: list[str] = []

            for edge in db.scalars(select(CampusEdge)):
                active, hard = stats.get(edge.id, (0, 0))
                weight = self.compute_edge_weight(
                    {
                        "distance_m": edge.distance_m,
                        "is_step_free": edge.is_step_free,
                        "active_barriers_count": active,
                    },
                    accessible_mode=True,
                    hard_blocks=hard,
                )
                finite_weight = (
                    edge.distance_m * (1.0 + settings.barrier_weight_multiplier * active)
                )
                edge.active_barriers_count = active
                edge.weight = round(finite_weight, 3)
                edge.step_free_blocked = bool(math.isinf(weight))
                if edge.step_free_blocked:
                    blocked.append(edge.id)
                if active:
                    penalised.append(edge.id)
                self._apply_edge_attrs(edge, active, hard, math.inf if math.isinf(weight) else finite_weight)

            db.flush()
            self._last_recompute_at = datetime.now(UTC)
            new_version = bump_graph_version(db)
            self._graph_version = new_version
            return {
                "edges_recomputed": len(self._edge_attrs),
                "penalised_edges": sorted(penalised),
                "blocked_edges": sorted(blocked),
                "graph_version": new_version,
            }

    def _apply_edge_attrs(
        self, edge: CampusEdge, active: int, hard: int, graph_weight: float
    ) -> None:
        """Push DB state into the in-memory graph (single source of truth)."""
        attrs = self._edge_attrs.get(edge.id)
        if attrs is None:
            return
        attrs["active_barriers_count"] = active
        attrs["hard_blocks"] = hard
        attrs["step_free_blocked"] = bool(hard)
        attrs["weight"] = graph_weight
        if self._graph is not None:
            for u, v in (
                (edge.source_node_id, edge.target_node_id),
                (edge.target_node_id, edge.source_node_id),
            ):
                if self._graph.has_edge(u, v, key=edge.id):
                    data = self._graph[u][v][edge.id]
                    data.update(
                        active_barriers_count=active,
                        hard_blocks=hard,
                        step_free_blocked=bool(hard),
                        weight=graph_weight,
                    )

    def sync_barrier_penalties(
        self, db: Session, edge_ids: Iterable[str | None]
    ) -> dict[str, Any]:
        """Refresh penalties after a barrier change and report what moved.

        Called on report / confirm / verify / resolve / reopen / expire. This is
        the mechanism that keeps the map, the database and the router consistent
        in real time.
        """
        targets = {edge_id for edge_id in edge_ids if edge_id}
        with self._lock:
            summary = self.recompute_weights(db)
            return {
                "updated_edges": sorted(targets),
                "blocked_edges": summary["blocked_edges"],
                "penalised_edges": summary["penalised_edges"],
                "edges_recomputed": summary["edges_recomputed"],
                "graph_version": summary["graph_version"],
                "touched_edge_blocked": sorted(targets & set(summary["blocked_edges"])),
                "touched_edge_penalised": sorted(targets & set(summary["penalised_edges"])),
                "recomputed_at": self._last_recompute_at.isoformat()
                if self._last_recompute_at
                else None,
            }

    # ------------------------------------------------------------------
    # Geo snapping
    # ------------------------------------------------------------------
    def nearest_node(
        self, db: Session, lat: float, lng: float, *, kinds: Sequence[str] | None = None
    ) -> tuple[str, float]:
        """Snap a GPS fix to the closest routable node (haversine)."""
        self.ensure_loaded(db)
        best_id: str | None = None
        best_dist = math.inf
        for node_id, attrs in self._node_attrs.items():
            if kinds and attrs.get("kind") not in kinds:
                continue
            dist = haversine_m(lat, lng, attrs["latitude"], attrs["longitude"])
            if dist < best_dist:
                best_id, best_dist = node_id, dist
        if best_id is None:
            raise LookupError("No routable nodes in the campus graph")
        return best_id, best_dist

    def nearest_edge(
        self, db: Session, lat: float, lng: float
    ) -> tuple[str | None, float, tuple[float, float]]:
        """Match a reported barrier to the closest path segment."""
        self.ensure_loaded(db)
        best_id: str | None = None
        best_dist = math.inf
        best_point = (lat, lng)
        for edge_id, attrs in self._edge_attrs.items():
            source = self._node_attrs.get(attrs["source_node_id"])
            target = self._node_attrs.get(attrs["target_node_id"])
            if source is None or target is None:
                continue
            dist, _t, proj_lat, proj_lng = _project_point_to_segment(
                lat,
                lng,
                source["latitude"],
                source["longitude"],
                target["latitude"],
                target["longitude"],
            )
            if dist < best_dist:
                best_id, best_dist, best_point = edge_id, dist, (proj_lat, proj_lng)
        return best_id, best_dist, best_point

    # ------------------------------------------------------------------
    # Routing
    # ------------------------------------------------------------------
    def find_accessible_route(
        self,
        db: Session,
        start_lat: float,
        start_lng: float,
        end_lat: float,
        end_lng: float,
        *,
        wheelchair_accessible: bool = True,
        avoid_construction: bool = False,
    ) -> dict[str, Any]:
        """Plan a campus route and return a GeoJSON-ready payload."""
        self.ensure_loaded(db)
        accessible = bool(wheelchair_accessible)

        start_node, start_snap = self.nearest_node(db, start_lat, start_lng)
        end_node, end_snap = self.nearest_node(db, end_lat, end_lng)

        warnings: list[dict[str, Any]] = []
        if start_snap > settings.max_snap_distance_m:
            warnings.append(
                _warning(
                    "far_start",
                    f"Start point is {start_snap:.0f} m from the nearest campus path; "
                    "routing from the closest node instead.",
                )
            )
        if end_snap > settings.max_snap_distance_m:
            warnings.append(
                _warning(
                    "far_end",
                    f"Destination is {end_snap:.0f} m from the nearest campus path.",
                )
            )

        if start_node == end_node:
            trivial = self._trivial_route(db, start_node, wheelchair_accessible=accessible)
            trivial["warnings"] = warnings
            return trivial

        # Strict pass: stairs are impassable in accessible mode, and any edge
        # carrying a hard-blocking barrier is severed outright.
        path = self._search(db, start_node, end_node, accessible=accessible, apply_hard_blocks=True)
        degraded = False

        if path is None and accessible:
            # Graceful degradation: every step-free chain is severed, so retry
            # without the hard-block cut (barriers fall back to their 10x
            # multiplicative penalty) and return the least-bad route with loud
            # warnings instead of an unhelpful 404.
            path = self._search(
                db, start_node, end_node, accessible=False, apply_hard_blocks=False
            )
            degraded = path is not None

        if path is None:
            return {
                "found": False,
                "reason": "no_route",
                "message": (
                    "No route exists between these points. The campus network may be "
                    "disconnected here, or a barrier has severed the only accessible link."
                ),
                "start_node": start_node,
                "end_node": end_node,
                "wheelchair_accessible": accessible,
                "warnings": warnings
                + [
                    _warning(
                        "no_route",
                        "Try a different destination or switch off step-free mode.",
                        severity="high",
                    )
                ],
            }

        payload = self._build_route_payload(
            db,
            path,
            accessible=accessible,
            degraded=degraded,
            start_coords=(start_lat, start_lng),
            end_coords=(end_lat, end_lng),
            start_snap=start_snap,
            end_snap=end_snap,
        )
        payload["warnings"] = warnings + payload["warnings"]

        if degraded:
            payload["warnings"].insert(
                0,
                _warning(
                    "step_free_severed",
                    "Every step-free route is currently blocked. The route shown "
                    "contains steps or a broken lift - please contact campus "
                    "operations or use the listed alternative entrance.",
                    severity="critical",
                ),
            )
            payload["blocked_edges"] = self.blocked_edge_ids()
        return payload

    def blocked_edge_ids(self) -> list[str]:
        """Edge ids currently severed by a hard-blocking barrier."""
        return sorted(
            edge_id
            for edge_id, attrs in self._edge_attrs.items()
            if attrs.get("step_free_blocked")
        )

    def _search(
        self,
        db: Session,
        start_node: str,
        end_node: str,
        *,
        accessible: bool,
        apply_hard_blocks: bool,
    ) -> list[dict[str, Any]] | None:
        """Run A* over a weighted view derived from the current barrier state.

        NetworkX's ``astar_path`` calls a callable ``weight`` with the raw edge
        attribute container, which for a MultiDiGraph is a dict-of-dicts. Rather
        than teach every call site that signature, we collapse the multi-graph
        into a plain DiGraph whose single edge per node pair is the *cheapest*
        parallel segment (ramp beats stairs, etc.). At campus scale this view
        costs microseconds to build and removes an entire class of bugs.
        """
        graph = self.graph
        speed = settings.speed_for(accessible)

        search_view = nx.DiGraph()
        for u, v, key, data in graph.edges(keys=True, data=True):
            weight = self.compute_edge_weight(
                data,
                accessible_mode=accessible,
                hard_blocks=int(data.get("hard_blocks") or 0) if apply_hard_blocks else 0,
            )
            if math.isinf(weight):
                continue  # physically impassable in this mode
            current = search_view.get_edge_data(u, v)
            if current is None or weight < current["weight"]:
                search_view.add_edge(u, v, weight=weight, edge_id=key)

        if start_node not in search_view or end_node not in search_view:
            return None

        goal = graph.nodes[end_node]

        def heuristic(u: str, _v: str) -> float:
            node = graph.nodes[u]
            return haversine_m(
                node["latitude"], node["longitude"], goal["latitude"], goal["longitude"]
            ) / max(speed, 0.1)

        try:
            node_path = nx.astar_path(
                search_view, start_node, end_node, heuristic=heuristic, weight="weight"
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
            logger.info("no path %s -> %s (%s)", start_node, end_node, exc.__class__.__name__)
            return None

        segments: list[dict[str, Any]] = []
        for u, v in zip(node_path, node_path[1:]):
            chosen = search_view.get_edge_data(u, v)
            if chosen is None:
                continue
            key = chosen["edge_id"]
            data = dict(graph[u][v][key])
            data["_weight"] = chosen["weight"]
            data["_from"] = u
            data["_to"] = v
            segments.append(data)
        return segments or None

    def _build_route_payload(
        self,
        db: Session,
        segments: list[dict[str, Any]],
        *,
        accessible: bool,
        degraded: bool,
        start_coords: tuple[float, float],
        end_coords: tuple[float, float],
        start_snap: float,
        end_snap: float,
    ) -> dict[str, Any]:
        graph = self.graph
        coordinates: list[list[float]] = []
        node_chain: list[str] = []

        for index, seg in enumerate(segments):
            u, v = seg["_from"], seg["_to"]
            nu, nv = graph.nodes[u], graph.nodes[v]
            if index == 0:
                node_chain.append(u)
                coordinates.append([nu["longitude"], nu["latitude"]])
            node_chain.append(v)
            coordinates.append([nv["longitude"], nv["latitude"]])

        latlng_path = [(c[1], c[0]) for c in coordinates]
        distance_m = polyline_length_m(latlng_path)
        speed = settings.speed_for(accessible)
        duration_s = distance_m / max(speed, 0.1)

        steps, deviation_warnings = self._build_instructions(db, segments, graph)
        # Advisories: barriers near (but not on) the route. Barriers actually on
        # the route arrive as per-step cautions, so filter them out here to stop
        # the warning list double-reporting the same hazard.
        on_route_ids = {c["barrier_id"] for step in steps for c in step.get("cautions", [])}
        on_route_ids |= {
            b.id for b in self._active_barriers_for_edges(db, [s["edge_id"] for s in segments])
        }
        warnings = deviation_warnings + [
            w for w in self._barriers_along_route(db, latlng_path) if w.get("barrier_id") not in on_route_ids
        ]

        incline_max = max((float(s.get("incline_pct") or 0.0) for s in segments), default=0.0)
        narrowest = min((float(s.get("width_m") or 99.0) for s in segments), default=99.0)
        stairs = [s for s in segments if not s.get("is_step_free", True)]

        if accessible:
            if stairs:
                warnings.append(
                    _warning(
                        "contains_steps",
                        f"{len(stairs)} segment(s) on this route are not step-free.",
                        severity="critical",
                    )
                )
            if incline_max >= 8.0:
                warnings.append(
                    _warning(
                        "steep_incline",
                        f"Steepest ramp on this route is {incline_max:.1f}% - above the "
                        "8% accessible design guidance.",
                        severity="high",
                    )
                )
            if narrowest < 1.5:
                warnings.append(
                    _warning(
                        "narrow_passage",
                        f"Narrowest point is {narrowest:.1f} m wide (min 1.5 m recommended "
                        "for wheelchair passing).",
                        severity="medium",
                    )
                )

        barriers_encountered = [
            barrier.to_dict(include_image=False)
            for barrier in self._active_barriers_for_edges(
                db, [s["edge_id"] for s in segments]
            )
        ]

        return {
            "found": True,
            "algorithm": "A*",
            "wheelchair_accessible": accessible,
            "degraded": degraded,
            "distance_m": round(distance_m, 1),
            "distance_text": _distance_text(distance_m),
            "duration_s": round(duration_s),
            "duration_min": round(duration_s / 60.0, 1),
            "duration_text": _duration_text(duration_s),
            "speed_mps": speed,
            "geometry": {"type": "LineString", "coordinates": coordinates},
            "geojson": {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coordinates},
                "properties": {
                    "wheelchair_accessible": accessible,
                    "degraded": degraded,
                    "distance_m": round(distance_m, 1),
                    "duration_min": round(duration_s / 60.0, 1),
                },
            },
            "node_path": node_chain,
            "edge_path": [s["edge_id"] for s in segments],
            "segments": [
                {
                    "edge_id": s["edge_id"],
                    "name": s.get("name"),
                    "kind": s.get("kind"),
                    "distance_m": round(float(s.get("distance_m") or 0.0), 1),
                    "is_step_free": bool(s.get("is_step_free", True)),
                    "width_m": s.get("width_m"),
                    "incline_pct": s.get("incline_pct"),
                    "active_barriers_count": int(s.get("active_barriers_count") or 0),
                    "weight": None
                    if math.isinf(s.get("_weight", math.inf))
                    else round(float(s.get("_weight") or 0.0), 2),
                }
                for s in segments
            ],
            "steps": steps,
            "warnings": warnings,
            "barriers_on_route": barriers_encountered,
            "coordinates": [[round(lat, 6), round(lng, 6)] for lat, lng in latlng_path],
            "start": {
                "requested": {
                    "latitude": start_coords[0],
                    "longitude": start_coords[1],
                },
                "node_id": node_chain[0] if node_chain else None,
                "snap_distance_m": round(start_snap, 1),
            },
            "end": {
                "requested": {
                    "latitude": end_coords[0],
                    "longitude": end_coords[1],
                },
                "node_id": node_chain[-1] if node_chain else None,
                "snap_distance_m": round(end_snap, 1),
            },
            "summary": {
                "accessibility_grade": _accessibility_grade(
                    accessible, degraded, stairs, incline_max, narrowest
                ),
                "max_incline_pct": round(incline_max, 1),
                "min_width_m": round(narrowest, 2) if narrowest < 99 else None,
                "step_free_segments": sum(1 for s in segments if s.get("is_step_free", True)),
                "total_segments": len(segments),
                "barrier_count": len(barriers_encountered),
            },
        }

    def _trivial_route(
        self, db: Session, node_id: str, *, wheelchair_accessible: bool
    ) -> dict[str, Any]:
        node = self.graph.nodes[node_id]
        point = [[node["longitude"], node["latitude"]]] * 2
        return {
            "found": True,
            "algorithm": "A*",
            "wheelchair_accessible": wheelchair_accessible,
            "degraded": False,
            "distance_m": 0.0,
            "distance_text": "0 m",
            "duration_s": 0,
            "duration_min": 0.0,
            "duration_text": "You are already there",
            "speed_mps": settings.speed_for(wheelchair_accessible),
            "geometry": {"type": "LineString", "coordinates": point},
            "geojson": {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": point},
                "properties": {"distance_m": 0.0, "duration_min": 0.0},
            },
            "node_path": [node_id],
            "edge_path": [],
            "segments": [],
            "steps": [
                {
                    "index": 0,
                    "action": ARRIVE,
                    "instruction": f"You are already at {node.get('name', node_id)}.",
                    "road_name": node.get("name", node_id),
                    "kind": "destination",
                    "distance_m": 0.0,
                    "cumulative_m": 0.0,
                    "heading_deg": None,
                    "compass": None,
                    "is_step_free": True,
                    "cautions": [],
                    "to_node": node_id,
                }
            ],
            "warnings": [],
            "barriers_on_route": [],
            "coordinates": [[node["latitude"], node["longitude"]]],
            "start": {"requested": None, "node_id": node_id, "snap_distance_m": 0.0},
            "end": {"requested": None, "node_id": node_id, "snap_distance_m": 0.0},
            "summary": {
                "accessibility_grade": "step_free",
                "max_incline_pct": 0.0,
                "min_width_m": None,
                "step_free_segments": 0,
                "total_segments": 0,
                "barrier_count": 0,
            },
        }

    # ------------------------------------------------------------------
    # Turn-by-turn generation
    # ------------------------------------------------------------------
    def _build_instructions(
        self, db: Session, segments: list[dict[str, Any]], graph: nx.MultiDiGraph
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Produce voice-ready, accessibility-aware turn-by-turn steps."""
        steps: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        cumulative = 0.0
        previous_bearing: float | None = None
        destination = graph.nodes[segments[-1]["_to"]] if segments else None

        for index, seg in enumerate(segments):
            u, v = seg["_from"], seg["_to"]
            nu, nv = graph.nodes[u], graph.nodes[v]
            bearing = bearing_deg(
                nu["latitude"], nu["longitude"], nv["latitude"], nv["longitude"]
            )
            distance = float(seg.get("distance_m") or 0.0)
            name = seg.get("name") or "pathway"
            kind = seg.get("kind", "footpath")

            if previous_bearing is None:
                action = "Start"
                instruction = f"Head {compass_label(bearing)} on {name}."
            else:
                delta = turn_delta_deg(previous_bearing, bearing)
                action, phrase = _classify_turn(delta)
                instruction = f"{phrase} onto {name}."

            cautions: list[dict[str, Any]] = []
            for barrier in self._active_barriers_for_edges(db, [seg["edge_id"]]):
                label = CATEGORY_LABELS.get(barrier.category, barrier.category)
                if barrier.is_hard_block:
                    text = (
                        f"In {distance:.0f} m, avoid {label.lower()} on {name} - "
                        "keep to the signed alternative."
                    )
                else:
                    text = (
                        f"In {distance:.0f} m, {label.lower()} reported on {name} - "
                        "expect a narrower line."
                    )
                cautions.append(
                    {
                        "type": "barrier",
                        "barrier_id": barrier.id,
                        "category": barrier.category,
                        "label": label,
                        "severity": CATEGORY_SEVERITY.get(barrier.category, 3),
                        "distance_m": round(distance, 1),
                        "at_distance_m": round(cumulative, 1),
                        "message": text,
                    }
                )
                warnings.append(
                    _warning(
                        "barrier_on_route",
                        text,
                        severity="critical" if barrier.is_hard_block else "high",
                        barrier_id=barrier.id,
                        distance_m=round(cumulative + distance, 1),
                    )
                )

            if kind == "stairs":
                instruction += " This segment has steps."
            elif kind == "ramp":
                instruction += f" Ramp incline {float(seg.get('incline_pct') or 0):.1f}%."
            elif kind == "elevator":
                instruction += " Take the lift."
            if float(seg.get("width_m") or 99.0) < 1.5:
                instruction += f" Path narrows to {float(seg['width_m']):.1f} m."

            steps.append(
                {
                    "index": index,
                    "action": action,
                    "instruction": instruction.strip(),
                    "road_name": name,
                    "kind": kind,
                    "distance_m": round(distance, 1),
                    "cumulative_m": round(cumulative + distance, 1),
                    "heading_deg": round(bearing, 1),
                    "compass": compass_label(bearing),
                    "is_step_free": bool(seg.get("is_step_free", True)),
                    "cautions": cautions,
                    "to_node": v,
                }
            )
            cumulative += distance
            previous_bearing = bearing

        if destination is not None:
            name = destination.get("name", "your destination")
            extra = ""
            if destination.get("has_elevator"):
                extra = " A lift is available inside."
            elif destination.get("is_entrance"):
                extra = " Step-free entrance."
            steps.append(
                {
                    "index": len(steps),
                    "action": ARRIVE,
                    "instruction": f"{ARRIVE}: {name}.{extra}",
                    "road_name": name,
                    "kind": "destination",
                    "distance_m": 0.0,
                    "cumulative_m": round(cumulative, 1),
                    "heading_deg": None,
                    "compass": None,
                    "is_step_free": True,
                    "cautions": [],
                    "to_node": segments[-1]["_to"],
                }
            )
        return steps, warnings

    # ------------------------------------------------------------------
    # Barrier lookups
    # ------------------------------------------------------------------
    def _active_barriers_for_edges(self, db: Session, edge_ids: Sequence[str]) -> list[Barrier]:
        ids = [edge_id for edge_id in edge_ids if edge_id]
        if not ids:
            return []
        rows = db.scalars(
            select(Barrier).where(
                Barrier.edge_id.in_(ids),
                Barrier.status.in_(ACTIVE_BARRIER_STATUSES),
            )
        )
        return [b for b in rows if b.is_active]

    def _barriers_along_route(
        self, db: Session, latlng_path: list[tuple[float, float]]
    ) -> list[dict[str, Any]]:
        """Barriers near (but not on) the route - the 'heads up' advisories."""
        if not latlng_path:
            return []
        active = db.scalars(
            select(Barrier).where(Barrier.status.in_(ACTIVE_BARRIER_STATUSES))
        )
        out: list[dict[str, Any]] = []
        for barrier in active:
            if not barrier.is_active:
                continue
            best_dist = math.inf
            best_ahead = 0.0
            for i in range(len(latlng_path) - 1):
                a_lat, a_lng = latlng_path[i]
                b_lat, b_lng = latlng_path[i + 1]
                dist, t, _plat, _plng = _project_point_to_segment(
                    barrier.latitude, barrier.longitude, a_lat, a_lng, b_lat, b_lng
                )
                if dist < best_dist:
                    best_dist = dist
                    best_ahead = polyline_length_m(latlng_path[: i + 1]) + t * haversine_m(
                        a_lat, a_lng, b_lat, b_lng
                    )
            if best_dist <= ALERT_RADIUS_M:
                label = CATEGORY_LABELS.get(barrier.category, barrier.category)
                out.append(
                    _warning(
                        "nearby_barrier",
                        f"{label} reported {best_dist:.0f} m from your route "
                        f"({best_ahead:.0f} m ahead).",
                        severity="high" if barrier.is_hard_block else "medium",
                        barrier_id=barrier.id,
                        distance_m=round(best_ahead, 1),
                    )
                )
        out.sort(key=lambda w: w.get("distance_m") or 0.0)
        return out[:6]

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def stats(self, db: Session) -> dict[str, Any]:
        """Graph diagnostics.

        ``step_free_components``/``isolated_step_free_zones`` describe the
        *topology* (barrier-independent). For the barrier-aware view - which
        facilities are unreachable right now - see
        ``GET /campus/accessibility-audit``.
        """
        self.ensure_loaded(db)
        graph = self.graph
        step_free = nx.MultiDiGraph()
        for u, v, key, data in graph.edges(keys=True, data=True):
            if data.get("is_step_free"):
                step_free.add_edge(u, v, key=key)
        for node_id, attrs in graph.nodes(data=True):
            if step_free.has_node(node_id):
                step_free.add_node(node_id, **attrs)

        components = (
            nx.number_weakly_connected_components(step_free) if step_free.number_of_nodes() else 0
        )
        blocked = self.blocked_edge_ids()
        segments = len(self._edge_attrs)
        step_free_segments = sum(
            1 for _e, d in self._edge_attrs.items() if d.get("is_step_free", True)
        )
        return {
            "nodes": graph.number_of_nodes(),
            # `edges` counts physical segments (what a person would call a path);
            # `directed_arcs` counts the bidirectional arcs actually in the graph.
            "edges": segments,
            "directed_arcs": graph.number_of_edges(),
            "step_free_edges": step_free_segments,
            "stairs_edges": segments - step_free_segments,
            "step_free_components": components,
            "isolated_step_free_zones": max(0, components - 1),
            "barrier_severed_edges": len(blocked),
            "barrier_severed_edge_ids": blocked,
            "buildings": sum(
                1 for _n, d in graph.nodes(data=True) if d.get("kind") == "building"
            ),
            "lift_nodes": sum(1 for _n, d in graph.nodes(data=True) if d.get("kind") == "lift"),
            "nodes_with_elevator": sum(
                1 for _n, d in graph.nodes(data=True) if d.get("has_elevator")
            ),
            "entrances": sum(1 for _n, d in graph.nodes(data=True) if d.get("is_entrance")),
            "barrier_penalised_edges": sum(
                1 for _e, d in self._edge_attrs.items() if d.get("active_barriers_count")
            ),
            "loaded_at": self._last_loaded_at.isoformat() if self._last_loaded_at else None,
            "graph_version": self._graph_version,
            "weights_recomputed_at": (
                self._last_recompute_at.isoformat() if self._last_recompute_at else None
            ),
            "reloads": self._load_count,
            "algorithm": "A* (haversine-admissible heuristic)",
            "speed_mps": {
                "walk": settings.walk_speed_mps,
                "wheelchair": settings.wheelchair_speed_mps,
            },
        }

    def edge_attrs(self, edge_id: str) -> dict[str, Any] | None:
        """Read-only view of the materialised attributes for one edge."""
        return self._edge_attrs.get(edge_id)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _classify_turn(delta_deg: float) -> tuple[str, str]:
    if abs(delta_deg) < 20:
        return CONTINUE, CONTINUE
    if 20 <= delta_deg < 55:
        return TURN_SLIGHT_RIGHT, TURN_SLIGHT_RIGHT
    if 55 <= delta_deg <= 135:
        return TURN_RIGHT, TURN_RIGHT
    if -55 < delta_deg <= -20:
        return TURN_SLIGHT_LEFT, TURN_SLIGHT_LEFT
    if -135 <= delta_deg <= -55:
        return TURN_LEFT, TURN_LEFT
    # near-reversal: model as a left turn (the pedestrian world has no U-turn)
    return TURN_LEFT, TURN_LEFT


def _warning(
    code: str,
    message: str,
    *,
    severity: str = "info",
    barrier_id: int | None = None,
    distance_m: float | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message, "severity": severity}
    if barrier_id is not None:
        payload["barrier_id"] = barrier_id
    if distance_m is not None:
        payload["distance_m"] = distance_m
    return payload


def _distance_text(distance_m: float) -> str:
    if distance_m < 1000:
        return f"{distance_m:.0f} m"
    return f"{distance_m / 1000:.2f} km"


def _duration_text(seconds: float) -> str:
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def _accessibility_grade(
    accessible: bool,
    degraded: bool,
    stairs: list[dict[str, Any]],
    incline_max: float,
    narrowest: float,
) -> str:
    if not accessible:
        return "standard"
    if degraded or stairs:
        return "not_step_free"
    if incline_max >= 8.0 or narrowest < 1.5:
        return "step_free_with_caution"
    return "step_free"


#: Module-level singleton - the API and the CV pipeline share one graph.
graph_service = GraphService()
