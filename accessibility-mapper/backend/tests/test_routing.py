"""Phase 2 acceptance tests: the routing engine and the scripted demo narratives."""

from __future__ import annotations

from app.services.graph_service import graph_service
from tests.conftest import HUB, HSB_CLINIC_L3, MORE_HALL, RED_SQUARE


def plan(client, start, end, wheelchair=True):
    response = client.post(
        "/api/v1/routes/plan",
        json={
            "start_lat": start[0],
            "start_lng": start[1],
            "end_lat": end[0],
            "end_lng": end[1],
            "wheelchair_accessible": wheelchair,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def blocked_ramp(client) -> dict:
    active = client.get("/api/v1/barriers/active").json()
    return next(
        feature["properties"]
        for feature in active["features"]
        if feature["properties"]["category"] == "blocked_ramp"
    )


def test_graph_loads_the_seeded_campus(client):
    stats = client.get("/api/v1/campus/graph/stats").json()
    assert stats["nodes"] >= 15, "seed script must provide at least 15 nodes"
    assert stats["edges"] >= 20, "seed script must provide at least 20 edges"
    assert stats["step_free_edges"] > 0
    assert stats["stairs_edges"] >= 1
    assert stats["buildings"] >= 20
    assert stats["algorithm"].startswith("A*")


def test_step_free_route_is_found_and_avoids_stairs(client):
    route = plan(client, RED_SQUARE, HUB, wheelchair=True)
    assert route["found"] is True
    assert route["degraded"] is False
    assert route["summary"]["accessibility_grade"] == "step_free"
    assert route["distance_m"] > 0
    assert route["duration_min"] > 0
    assert route["geometry"]["type"] == "LineString"
    for segment in route["segments"]:
        assert segment["is_step_free"] is True, "a wheelchair route must never use stairs"
    assert route["steps"], "turn-by-turn instructions are required"
    assert route["steps"][0]["instruction"]
    assert route["steps"][-1]["action"] == "Arrive at destination"


def test_walking_route_may_use_stairs(client):
    walking = plan(client, RED_SQUARE, MORE_HALL, wheelchair=False)
    assert walking["found"] is True
    assert walking["degraded"] is False
    assert walking["summary"]["accessibility_grade"] == "standard"


def test_blocked_ramp_severs_the_step_free_chain(client):
    """More Hall's only step-free approach is the ramp carrying a blocked_ramp."""
    route = plan(client, RED_SQUARE, MORE_HALL, wheelchair=True)
    assert route["found"] is True
    assert route["degraded"] is True, "expected graceful degradation, not a 404"
    assert route["summary"]["accessibility_grade"] == "not_step_free"
    assert any(w["code"] == "step_free_severed" for w in route["warnings"])
    assert "e_more_ramp" in route["blocked_edges"]


def test_broken_lift_makes_lift_only_clinic_unreachable(client):
    route = plan(client, RED_SQUARE, HSB_CLINIC_L3, wheelchair=True)
    assert route["found"] is True
    assert route["degraded"] is True
    assert any(
        w["code"] == "step_free_severed" for w in route["warnings"]
    ), "a broken lift on the only lift edge must trigger a hard warning"


def test_resolve_then_reopen_round_trip_updates_the_graph(client, admin_token):
    """Resolving clears the penalty; reopening restores it. State is left intact."""
    headers = {"Authorization": f"Bearer {admin_token}"}
    barrier = blocked_ramp(client)

    before = plan(client, RED_SQUARE, MORE_HALL, wheelchair=True)
    assert before["degraded"] is True
    assert "e_more_ramp" not in before["edge_path"]

    resolved = client.patch(
        f"/api/v1/admin/barriers/{barrier['id']}/resolve",
        json={"resolution_note": "Scooters removed by campus ops."},
        headers=headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["barrier"]["status"] == "resolved"

    after = plan(client, RED_SQUARE, MORE_HALL, wheelchair=True)
    assert after["found"] is True
    assert after["degraded"] is False, "clearing the barrier must reopen the step-free route"
    assert after["summary"]["accessibility_grade"] in ("step_free", "step_free_with_caution")
    assert "e_more_ramp" in after["edge_path"], "route should now use the reopened ramp"
    assert all(segment["is_step_free"] for segment in after["segments"])

    reopened = client.post(
        f"/api/v1/admin/barriers/{barrier['id']}/reopen",
        json={"reason": "Blocked again within the hour - recurring hotspot."},
        headers=headers,
    )
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["barrier"]["status"] == "verified"

    restored = plan(client, RED_SQUARE, MORE_HALL, wheelchair=True)
    assert restored["degraded"] is True, "reopening must re-sever the step-free chain"


def test_route_plan_validates_coordinates(client):
    bad = client.post(
        "/api/v1/routes/plan",
        json={
            "start_lat": 200,
            "start_lng": 0,
            "end_lat": 0,
            "end_lng": 0,
            "wheelchair_accessible": True,
        },
    )
    assert bad.status_code == 422


def test_trivial_route_when_already_at_destination(client):
    route = plan(client, MORE_HALL, MORE_HALL, wheelchair=True)
    assert route["found"] is True
    assert route["distance_m"] == 0
    assert route["steps"][0]["action"] == "Arrive at destination"


def test_planner_surfaces_hazards_to_the_traveller(client):
    route = plan(client, RED_SQUARE, HUB, wheelchair=True)
    caution_messages = [
        caution["message"] for step in route["steps"] for caution in step.get("cautions", [])
    ]
    assert caution_messages or route["warnings"], "hazards must be surfaced to the user"
    for warning in route["warnings"]:
        assert warning["severity"] in ("info", "medium", "high", "critical")
        assert warning["message"]


def test_accessibility_audit_lists_isolated_facilities(client):
    audit = client.get("/api/v1/campus/accessibility-audit").json()
    assert audit["step_free_graph"]["nodes"] > 0
    assert audit["unreachable_count"] >= 1
    names = [item["name"] for item in audit["unreachable_facilities"]]
    assert any("More Hall" in name or "Clinic" in name for name in names)


def test_weight_formula_is_applied_to_touched_edges(client):
    weights = client.get("/api/v1/barriers/graph/weights").json()
    assert weights["barrier_multiplier"] == 10.0
    penalised = [edge for edge in weights["edges"] if edge["penalised"]]
    assert penalised, "at least one edge must carry the dynamic penalty"
    for edge in penalised:
        assert edge["weight"] > edge["distance_m"]


def test_nearest_edge_matching_pulls_reports_onto_the_network(client, db_session):
    """A GPS fix near More Hall must snap onto one of its incident segments."""
    offset = (MORE_HALL[0] + 0.00010, MORE_HALL[1] - 0.00010)  # ~15 m off
    edge_id, distance, point = graph_service.nearest_edge(db_session, *offset)
    assert edge_id is not None
    assert distance < 40.0
    assert point != offset, "the projection must move the report onto the segment"
    node = client.get("/api/v1/campus/nodes/bld_more").json()
    incident = {edge["id"] for edge in node["edges"]}
    assert edge_id in incident
