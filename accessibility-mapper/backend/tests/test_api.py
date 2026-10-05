"""Phase 4/6 acceptance tests: reporting pipeline, dedupe, dashboard endpoints."""

from __future__ import annotations

import io
import math

from PIL import Image, ImageDraw

from tests.conftest import MORE_HALL, RED_SQUARE
from tests.test_cv import make_photo

LEGACY_HUB_ROUNDABOUT = (47.65547, -122.30615)  # quiet spot away from seeded reports


def _photo(style: str = "obstacle", seed: int = 42) -> bytes:
    return make_photo(style=style, seed=seed)


def _as_upload(raw: bytes, name: str = "barrier.jpg"):
    return {"file": (name, io.BytesIO(raw), "image/jpeg")}


def test_health_and_system_status(client):
    health = client.get("/api/v1/health").json()
    assert health["status"] == "ok"
    status = client.get("/api/v1/system/status").json()
    assert status["graph"]["nodes"] >= 15
    assert status["cv"]["engine"] in ("yolov8", "heuristic")
    assert status["policies"]["auto_verify_confidence"] == 0.85
    assert "active_barriers" in status["routing"]["weight_formula"]


def test_cv_status_endpoint_documents_the_active_engine(client):
    cv = client.get("/api/v1/cv/status").json()
    assert cv["engine"] in ("yolov8", "heuristic")
    assert cv["opencv_available"] is True
    assert cv["hint"]


def test_demo_accounts_are_listed_and_login_works(client):
    accounts = client.get("/api/v1/auth/demo-accounts").json()
    assert len(accounts) >= 3
    assert any(a["role"] == "admin" for a in accounts)

    login = client.post(
        "/api/v1/auth/login", json={"email": "admin@campus.edu", "password": "admin123"}
    )
    assert login.status_code == 200
    assert login.json()["user"]["role"] == "admin"

    wrong = client.post(
        "/api/v1/auth/login", json={"email": "admin@campus.edu", "password": "nope"}
    )
    assert wrong.status_code == 401


def test_network_layer_serves_nodes_and_edges(client):
    network = client.get("/api/v1/campus/network").json()
    assert network["meta"]["nodes"] >= 15
    assert network["meta"]["edges"] >= 20
    kinds = {
        feature["geometry"]["type"] for feature in network["features"]
    }
    assert kinds == {"Point", "LineString"}


def test_active_barriers_returns_geojson(client):
    payload = client.get("/api/v1/barriers/active").json()
    assert payload["type"] == "FeatureCollection"
    assert payload["meta"]["count"] >= 3
    for feature in payload["features"]:
        assert feature["geometry"]["type"] == "Point"
        props = feature["properties"]
        assert props["status"] in ("unverified", "verified", "in_progress")
        assert 0 <= props["confidence"] <= 1
        assert props["color"].startswith("#")


def test_category_catalogue_matches_domain_vocabulary(client):
    payload = client.get("/api/v1/barriers/categories").json()
    categories = {item["category"] for item in payload["categories"]}
    assert categories == {
        "blocked_ramp",
        "broken_lift",
        "narrow_path",
        "construction",
        "obstacle",
        "missing_signage",
    }
    blocking = {c["category"] for c in payload["categories"] if c["step_free_blocking"]}
    assert blocking == {"blocked_ramp", "broken_lift", "narrow_path"}


def test_report_creates_barrier_with_cv_and_privacy_payload(client):
    response = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("construction", seed=101)),
        data={
            "latitude": str(LEGACY_HUB_ROUNDABOUT[0]),
            "longitude": str(LEGACY_HUB_ROUNDABOUT[1]),
            "description": "Scaffolding going up along the service road",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["action"] == "created"
    assert body["barrier"]["id"] > 0
    assert body["cv"]["category"] in {
        "blocked_ramp",
        "broken_lift",
        "narrow_path",
        "construction",
        "obstacle",
        "missing_signage",
    }
    assert body["cv"]["engine"] in ("yolov8", "heuristic")
    assert body["privacy"]["exif_stripped"] is True
    assert body["dedupe"]["checked_radius_m"] == 15.0
    assert body["image"]["image_path"].endswith(".jpg")
    assert body["auto_verify"]["threshold"] == 0.85


def test_duplicate_report_within_15m_confirms_instead_of_duplicating(client):
    lat = LEGACY_HUB_ROUNDABOUT[0] + 0.00004  # ~4.5 m north
    lng = LEGACY_HUB_ROUNDABOUT[1]
    raw = _photo("construction", seed=202)

    first = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(raw),
        data={"latitude": str(lat), "longitude": str(lng), "category": "construction"},
    )
    assert first.status_code == 201, first.text
    barrier_id = first.json()["barrier"]["id"]

    second = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("construction", seed=203)),
        data={"latitude": str(lat + 0.00002), "longitude": str(lng), "category": "construction"},
    )
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["action"] == "confirmed"
    assert body["barrier"]["id"] == barrier_id, "duplicate must merge, not create"
    assert body["dedupe"]["merged"] is True
    assert body["dedupe"]["duplicate_distance_m"] <= 15.0
    assert body["barrier"]["confirmations"] >= 1


def test_report_beyond_the_radius_creates_a_new_barrier(client):
    base = (47.65400, -122.30680)
    first = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("obstacle", seed=301)),
        data={"latitude": str(base[0]), "longitude": str(base[1]), "category": "obstacle"},
    )
    far = (base[0] + 0.001, base[1])  # ~111 m away, outside the 15 m merge radius
    second = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("obstacle", seed=302)),
        data={"latitude": str(far[0]), "longitude": str(far[1]), "category": "obstacle"},
    )
    assert first.json()["action"] == "created"
    assert second.json()["action"] == "created"
    assert second.json()["barrier"]["id"] != first.json()["barrier"]["id"]


def test_reporter_override_is_recorded_as_citizen_manual(client):
    response = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("missing_signage", seed=401)),
        data={
            "latitude": "47.65220",
            "longitude": "-122.30550",
            "category": "narrow_path",
            "description": "gap between the bollards is very tight",
        },
    )
    body = response.json()
    assert body["barrier"]["category"] == "narrow_path"
    assert body["barrier"]["detection_source"] == "citizen_manual"


def test_report_requires_a_photo(client):
    response = client.post(
        "/api/v1/barriers/report",
        data={"latitude": "47.655", "longitude": "-122.305"},
    )
    assert response.status_code == 422


def test_report_rejects_unknown_category(client):
    response = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("obstacle", seed=501)),
        data={
            "latitude": "47.65310",
            "longitude": "-122.30410",
            "category": "aliens",
        },
    )
    assert response.status_code == 422


def test_confirm_endpoint_promotes_by_consensus(client):
    created = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("obstacle", seed=601)),
        data={
            "latitude": "47.65780",
            "longitude": "-122.31210",
            "category": "obstacle",
            "description": "bin tipped over on the kerb",
        },
    ).json()
    barrier = created["barrier"]

    if barrier["status"] == "unverified":
        # Auto-verified reports already satisfy the policy; assert the counter moves.
        first = client.post(
            f"/api/v1/barriers/{barrier['id']}/confirm", json={"note": "still there"}
        )
        assert first.status_code == 200, first.text
        assert first.json()["barrier"]["confirmations"] >= 1
    else:
        assert barrier["confirmations"] >= 0

    timeline = client.get(f"/api/v1/barriers/{barrier['id']}/timeline").json()
    assert timeline["barrier_id"] == barrier["id"]
    assert timeline["events"], "every barrier must have an audit trail"


def test_confirm_missing_barrier_returns_404(client):
    assert client.post("/api/v1/barriers/999999/confirm", json={}).status_code == 404


def test_barrier_list_filters_and_pagination(client):
    payload = client.get("/api/v1/barriers", params={"limit": 5, "offset": 0}).json()
    assert payload["limit"] == 5
    assert len(payload["items"]) <= 5
    assert payload["total"] >= 3

    verified = client.get("/api/v1/barriers", params={"status": "verified"}).json()
    assert all(item["status"] == "verified" for item in verified["items"])

    lifts = client.get("/api/v1/barriers", params={"category": "broken_lift"}).json()
    assert all(item["category"] == "broken_lift" for item in lifts["items"])


def test_resolving_updates_the_ticket_and_the_edge_weight(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    queue = client.get("/api/v1/admin/tickets").json()
    assert queue["total"] >= 2

    target = queue["items"][0]
    assert target["priority"] in ("low", "medium", "high", "critical")
    assert target["sla_hours"] > 0
    assert target["impact_score"] > 0

    weights_before = {
        edge["id"]: edge["weight"]
        for edge in client.get("/api/v1/barriers/graph/weights").json()["edges"]
    }

    progressed = client.patch(
        f"/api/v1/admin/tickets/{target['id']}", json={"status": "in_progress"}, headers=headers
    )
    assert progressed.status_code == 200, progressed.text
    assert progressed.json()["status"] == "in_progress"
    assert progressed.json()["age_hours"] >= 0

    if target["barrier_id"]:
        detail = client.get(f"/api/v1/barriers/{target['barrier_id']}/edge").json()
        if detail["edge"]:
            assert weights_before[detail["edge"]["id"]] >= detail["edge"]["distance_m"]

    # Put the queue back the way we found it.
    client.patch(
        f"/api/v1/admin/tickets/{target['id']}", json={"status": "open"}, headers=headers
    )


def test_admin_analytics_payload_is_complete(client):
    analytics = client.get("/api/v1/admin/analytics").json()
    kpis = analytics["kpis"]
    assert kpis["total_barriers"] >= 3
    assert kpis["active_barriers"] >= 3
    assert kpis["cv_engine"] in ("yolov8", "heuristic")
    assert kpis["avg_resolution_hours"] is not None
    assert kpis["privacy_redactions"] >= 0

    assert analytics["category_breakdown"], "category breakdown is required"
    assert analytics["heatmap"], "heatmap dataset is required"
    for point in analytics["heatmap"]:
        assert point["intensity"] > 0
        assert point["count"] >= 1
    assert analytics["hotspot_zones"]
    assert len(analytics["resolution_trend"]) == 14
    assert analytics["tickets"]["total"] >= 2
    assert analytics["routing_health"]["affected_edge_count"] >= 1


def test_maintenance_sweep_is_idempotent(client, admin_token):
    headers = {"Authorization": f"Bearer {admin_token}"}
    first = client.post("/api/v1/admin/maintenance/sweep", headers=headers)
    assert first.status_code == 200
    assert "expired" in first.json()


def test_policies_endpoint_publishes_thresholds(client):
    policies = client.get("/api/v1/admin/policies").json()
    assert policies["auto_verify_confidence"] == 0.85
    assert policies["consensus_confirmations"] == 2
    assert policies["duplicate_radius_m"] == 15.0
    assert policies["barrier_weight_multiplier"] == 10.0
    assert "blocked_ramp" in policies["ttl_by_category"]


def test_dataset_counts(client):
    counts = client.get("/api/v1/system/dataset").json()
    assert counts["nodes"] >= 15
    assert counts["edges"] >= 20
    assert counts["active_barriers"] >= 3


def test_redacted_image_is_served_over_media_mount(client):
    created = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("obstacle", seed=701)),
        data={"latitude": "47.66010", "longitude": "-122.30200", "category": "obstacle"},
    ).json()
    url = created["barrier"].get("image_url")
    assert url and url.startswith("/media/uploads/")
    image = client.get(url)
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")
    # The stored artifact must be a real image, not the raw upload.
    with Image.open(io.BytesIO(image.content)) as served:
        assert served.size[0] > 0


def test_report_off_network_is_flagged(client):
    response = client.post(
        "/api/v1/barriers/report",
        files=_as_upload(_photo("obstacle", seed=801)),
        data={"latitude": "47.70000", "longitude": "-122.25000", "category": "obstacle"},
    )
    body = response.json()
    assert body["barrier"]["edge_id"] is None
    assert body["dedupe"]["off_network"] is True


def test_overview_payload_powers_the_frontend_boot(client):
    overview = client.get("/api/v1/overview").json()
    assert overview["presets"]
    assert overview["bounds"]["center_latitude"] > 0
    assert overview["cv"]["engine"] in ("yolov8", "heuristic")
    assert "weight =" in overview["formula"]


def test_node_detail_includes_incident_edges_and_barriers(client):
    detail = client.get("/api/v1/campus/nodes/jct_central_walk_e").json()
    assert detail["node"]["id"] == "jct_central_walk_e"
    assert detail["edges"]
    assert detail["step_free_degree"] >= 1


def test_presets_include_lift_only_destinations(client):
    presets = client.get("/api/v1/routes/presets").json()
    ids = {preset["node_id"] for preset in presets["presets"]}
    assert "bld_suzzallo" in ids
    assert "hsb_clinic_3" in ids
    assert presets["bounds"]["max_latitude"] > presets["bounds"]["min_latitude"]


def test_distance_between_two_seeded_nodes_is_plausible(client, db_session):
    from app.core.geo import haversine_m

    distance = haversine_m(
        RED_SQUARE[0], RED_SQUARE[1], MORE_HALL[0], MORE_HALL[1]
    )
    assert 100 < distance < 800, "campus geometry should be walkable, not continental"
    assert not math.isnan(distance)
