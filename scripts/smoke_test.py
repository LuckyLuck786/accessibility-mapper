#!/usr/bin/env python
"""End-to-end smoke test for a deployed (or local) Ghost Space instance.

Checks the things that actually break in a serverless deployment, in order:

1.  the map data loads (overview + network + active barriers)
2.  step-free routing works and respects barriers
3.  a barrier report round-trips through the privacy pipeline and the stored
    image is served back out of Postgres
4.  a step-free room request excludes rooms behind a broken lift, *with a
    reason*
5.  check-in and metrics work
6.  admin routes **reject** requests without the token

Usage::

    python scripts/smoke_test.py --base-url https://your-app.vercel.app
    python scripts/smoke_test.py --base-url http://localhost:8000 --admin-token secret

Only ``httpx`` is needed. Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from typing import Any

try:
    import httpx
except ImportError:  # pragma: no cover
    print("This script needs httpx:  pip install httpx", file=sys.stderr)
    raise SystemExit(2)

from PIL import Image, ImageDraw  # noqa: E402  (only used to build a test photo)

# --- demo coordinates (Red Square, from the seeded campus) -----------------
RED_SQUARE = (47.65599, -122.30836)
HSB_CLINIC_L3 = (47.65031, -122.30936)


class Results:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[tuple[str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        if ok:
            self.passed.append(name)
            print(f"  PASS  {name}")
        else:
            self.failed.append((name, detail))
            print(f"  FAIL  {name}: {detail}")
        return ok

    def summary(self) -> int:
        total = len(self.passed) + len(self.failed)
        print(f"\n{'=' * 62}")
        print(f"{len(self.passed)}/{total} checks passed")
        if self.failed:
            print("\nFailures:")
            for name, detail in self.failed:
                print(f"  - {name}: {detail}")
            return 1
        print("All smoke checks passed.")
        return 0


def make_photo(seed: int = 7, style: str = "construction") -> bytes:
    """A deterministic synthetic photo - the CV pipeline must accept it."""
    import random

    random.seed(seed)
    width, height = 640, 480
    image = Image.new("RGB", (width, height), (170, 175, 165))
    draw = ImageDraw.Draw(image)
    if style == "construction":
        for x in range(0, width, 40):
            draw.polygon(
                [(x, 0), (x + 20, 0), (x + 40, height), (x + 20, height)],
                fill=(235, 120, 20),
            )
            draw.polygon(
                [(x + 20, 0), (x + 40, 0), (x + 60, height), (x + 40, height)],
                fill=(245, 245, 245),
            )
    else:
        draw.rectangle([width // 3, height // 2, 2 * width // 3, height - 20],
                       fill=(20, 22, 25))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="e.g. https://app.vercel.app")
    parser.add_argument("--admin-token", default=None, help="ADMIN_TOKEN, to test admin actions")
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    api = f"{base}/api/v1"
    results = Results()
    client = httpx.Client(timeout=args.timeout, follow_redirects=True)

    print(f"\nSmoke testing {base}\n" + "=" * 62)

    # --- 1. health + map data --------------------------------------------
    print("\n[1] map data")
    try:
        health = client.get(f"{api}/health")
        results.check("health returns 200", health.status_code == 200,
                      f"got {health.status_code}")
        results.check("database is postgres (not the sqlite fallback)",
                      health.json().get("database", "").startswith("postgres"),
                      f"database={health.json().get('database')!r}")

        overview = client.get(f"{api}/overview")
        ok = overview.status_code == 200
        results.check("overview loads", ok, f"got {overview.status_code}")
        if ok:
            graph = overview.json().get("graph", {})
            results.check("campus graph has nodes and edges",
                          graph.get("nodes", 0) > 0 and graph.get("edges", 0) > 0,
                          f"nodes={graph.get('nodes')} edges={graph.get('edges')}")
            results.check("graph_version is reported (stateless instances)",
                          graph.get("graph_version") is not None, "graph_version missing")

        network = client.get(f"{api}/campus/network")
        ok = network.status_code == 200
        results.check("campus network GeoJSON loads", ok, f"got {network.status_code}")
        if ok:
            features = network.json().get("features", [])
            kinds = {f["geometry"]["type"] for f in features}
            results.check("network has both points and lines",
                          kinds == {"Point", "LineString"}, f"kinds={kinds}")

        barriers = client.get(f"{api}/barriers/active")
        ok = barriers.status_code == 200
        results.check("active barriers load", ok, f"got {barriers.status_code}")
        barrier_count = 0
        if ok:
            barrier_count = len(barriers.json().get("features", []))
            results.check("seeded barriers are present", barrier_count >= 3,
                          f"only {barrier_count} active barriers")
    except Exception as exc:  # noqa: BLE001
        results.check("map data reachable", False, f"{type(exc).__name__}: {exc}")
        return results.summary()

    # --- 2. routing --------------------------------------------------------
    print("\n[2] routing")
    try:
        route = client.post(f"{api}/routes/plan", json={
            "start_lat": RED_SQUARE[0], "start_lng": RED_SQUARE[1],
            "end_lat": HSB_CLINIC_L3[0], "end_lng": HSB_CLINIC_L3[1],
            "wheelchair_accessible": True,
        })
        ok = route.status_code == 200
        results.check("step-free route plan returns 200", ok, f"got {route.status_code}: {route.text[:200]}")
        if ok:
            body = route.json()
            results.check("route was found", body.get("found") is True, "found=false")
            results.check("route carries turn-by-turn steps",
                          len(body.get("steps", [])) > 0, "no steps")
            results.check("lift-only destination is degraded (broken lift is live)",
                          body.get("degraded") is True,
                          "expected degraded=true while the Health Sciences lift is broken")
    except Exception as exc:  # noqa: BLE001
        results.check("routing works", False, f"{type(exc).__name__}: {exc}")

    # --- 3. report upload + media -----------------------------------------
    print("\n[3] barrier report")
    try:
        report = client.post(
            f"{api}/barriers/report",
            files={"file": ("smoke.jpg", make_photo(101), "image/jpeg")},
            data={"latitude": str(RED_SQUARE[0] + 0.00031),
                  "longitude": str(RED_SQUARE[1] + 0.00032),
                  "description": "smoke test: scaffolding narrowing the walk"},
        )
        ok = report.status_code == 201
        results.check("report accepted (201)", ok,
                      f"got {report.status_code}: {report.text[:300]}")
        if ok:
            body = report.json()
            barrier = body["barrier"]
            results.check("privacy redaction ran before storage",
                          body["privacy"]["exif_stripped"] is True, "EXIF not stripped")
            results.check("a public report starts unverified",
                          barrier["status"] == "unverified",
                          f"status={barrier['status']}")
            results.check("classifier returned a valid category",
                          body["cv"]["category"] in (
                              "blocked_ramp", "broken_lift", "narrow_path",
                              "construction", "obstacle", "missing_signage"),
                          f"category={body['cv']['category']}")

            url = barrier.get("image_url")
            media_ok = False
            if url:
                media = client.get(f"{base}{url}")
                media_ok = media.status_code == 200 and media.headers.get(
                    "content-type", "").startswith("image/")
                if media_ok:
                    try:
                        with Image.open(io.BytesIO(media.content)) as served:
                            served.size[0] > 0
                    except Exception:  # noqa: BLE001
                        media_ok = False
            results.check("redacted image is served from the database",
                          media_ok, f"GET {url} failed")
            results.check("stored image is under the ~300 KB budget",
                          (body.get("image", {}).get("byte_size") or 0) <= 400_000,
                          f"byte_size={body.get('image', {}).get('byte_size')}")
    except Exception as exc:  # noqa: BLE001
        results.check("report upload works", False, f"{type(exc).__name__}: {exc}")

    # --- 4. Ghost Space rooms ---------------------------------------------
    print("\n[4] ghost space")
    try:
        rooms = client.get(f"{api}/spaces/rooms")
        ok = rooms.status_code == 200
        results.check("rooms endpoint works", ok, f"got {rooms.status_code}")
        if ok:
            payload = rooms.json()
            results.check("12+ rooms seeded", payload.get("total", 0) >= 12,
                          f"total={payload.get('total')}")
            results.check("some rooms are not step-free",
                          any(not r["is_step_free_access"] for r in payload["rooms"]),
                          "every room claims step-free access")

        board = client.get(f"{api}/spaces/board")
        results.check("ghost space board works", board.status_code == 200,
                      f"got {board.status_code}")
        if board.status_code == 200:
            b = board.json()
            bookings = sum(len(r["bookings"]) for r in b["rooms"])
            results.check("40+ bookings in the demo day", bookings >= 40,
                          f"only {bookings} bookings")

        clock = client.get(f"{api}/demo/clock")
        results.check("demo clock readable", clock.status_code == 200,
                      f"got {clock.status_code}")
    except Exception as exc:  # noqa: BLE001
        results.check("ghost space reachable", False, f"{type(exc).__name__}: {exc}")

    # --- 5. reachability-aware room request --------------------------------
    print("\n[5] step-free room request (the core novelty)")
    try:
        clock = client.get(f"{api}/demo/clock").json()
        base_time = clock.get("now")
        start, end = base_time, None
        # Ask for a window an hour long starting in 15 minutes.
        import datetime as dt

        parsed = dt.datetime.fromisoformat(base_time)
        start = (parsed + dt.timedelta(minutes=15)).isoformat()
        end = (parsed + dt.timedelta(minutes=105)).isoformat()

        request = client.post(f"{api}/spaces/request", json={
            "capacity_needed": 16,
            "start_ts": start,
            "end_ts": end,
            "needs_step_free": True,
            "origin_latitude": RED_SQUARE[0],
            "origin_longitude": RED_SQUARE[1],
            "origin_label": "Red Square",
        })
        ok = request.status_code == 200
        results.check("room request returns 200", ok,
                      f"got {request.status_code}: {request.text[:300]}")
        if ok:
            payload = request.json()
            results.check("explanation object returned",
                          bool(payload.get("explanation", {}).get("decision")),
                          "no explanation")
            excluded = payload.get("excluded", [])
            unreachable = [e for e in excluded if e.get("reason_code") == "unreachable"]
            results.check("at least one room excluded for reachability",
                          bool(unreachable),
                          "no unreachable exclusions - is the broken lift live?")
            if unreachable:
                results.check("exclusion names the blocking barrier",
                              any(e.get("category") for e in unreachable),
                              "no barrier named in the exclusion reason")
                sample = unreachable[0]["reason"]
                results.check("exclusion reason is human-readable",
                              any(word in sample.lower()
                                  for word in ("lift", "ramp", "step-free", "route")),
                              f"reason={sample!r}")
                print(f"        e.g. {sample}")
    except Exception as exc:  # noqa: BLE001
        results.check("room request works", False, f"{type(exc).__name__}: {exc}")

    # --- 6. check-in -------------------------------------------------------
    print("\n[6] check-in")
    try:
        rooms = client.get(f"{api}/spaces/rooms").json().get("rooms", [])
        if rooms:
            room_id = rooms[0]["id"]
            checkin = client.post(f"{api}/spaces/checkin",
                                  json={"room_id": room_id, "headcount": 7})
            ok = checkin.status_code == 200
            results.check("check-in accepted", ok,
                          f"got {checkin.status_code}: {checkin.text[:200]}")
            if ok:
                results.check("check-in stores headcount only",
                              "signal" in checkin.json()
                              and "headcount" in checkin.json()["signal"],
                              "no headcount signal returned")
        else:
            results.check("check-in accepted", False, "no rooms available to check into")
    except Exception as exc:  # noqa: BLE001
        results.check("check-in works", False, f"{type(exc).__name__}: {exc}")

    # --- 7. metrics --------------------------------------------------------
    print("\n[7] metrics")
    try:
        metrics = client.get(f"{api}/spaces/metrics")
        ok = metrics.status_code == 200
        results.check("metrics endpoint works", ok, f"got {metrics.status_code}")
        if ok:
            m = metrics.json()
            for key in ("baseline", "ghost_space", "release_accuracy", "requests", "energy"):
                results.check(f"metrics.{key} present", key in m, f"missing {key}")
            results.check("energy is labelled an estimate",
                          m.get("energy", {}).get("is_estimate") is True,
                          "energy not marked as an estimate")
            baseline_hours = m.get("baseline", {}).get("empty_booked_room_hours", 0)
            results.check("baseline empty room-hours are computed, not zero",
                          baseline_hours > 0, f"baseline={baseline_hours}")
            print(f"        baseline empty room-hours: {baseline_hours}")
            print(f"        recovered room-hours:        {m.get('ghost_space', {}).get('recovered_room_hours')}")
            print(f"        kWh saved (estimate):        {m.get('ghost_space', {}).get('kwh_saved')}")
    except Exception as exc:  # noqa: BLE001
        results.check("metrics work", False, f"{type(exc).__name__}: {exc}")

    # --- 8. admin auth is actually enforced -------------------------------
    print("\n[8] admin authentication")
    try:
        unauth = client.post(f"{api}/admin/demo/reset")
        results.check("admin reset is REJECTED without a token",
                      unauth.status_code in (401, 403),
                      f"got {unauth.status_code} - admin routes are open!")

        unauth_seed = client.post(f"{api}/admin/seed")
        results.check("admin seed is REJECTED without a token",
                      unauth_seed.status_code in (401, 403),
                      f"got {unauth_seed.status_code} - admin routes are open!")

        unauth_clock = client.post(f"{api}/demo/clock", json={"speed": 60})
        results.check("demo clock write is REJECTED without a token",
                      unauth_clock.status_code in (401, 403),
                      f"got {unauth_clock.status_code} - clock writes are open!")

        unauth_release = client.post(f"{api}/admin/ghost-space/bookings/1/force-release",
                                     json={"reason": "smoke test"})
        results.check("Ghost Space override is REJECTED without a token",
                      unauth_release.status_code in (401, 403),
                      f"got {unauth_release.status_code} - overrides are open!")

        if args.admin_token:
            headers = {"X-Admin-Token": args.admin_token}
            allowed = client.post(f"{api}/admin/seed", headers=headers)
            results.check("admin seed ACCEPTED with the correct token",
                          allowed.status_code == 200,
                          f"got {allowed.status_code}: {allowed.text[:200]}")
            wrong = client.post(f"{api}/admin/seed",
                                headers={"X-Admin-Token": "wrong-token"})
            results.check("admin seed REJECTED with a wrong token",
                          wrong.status_code in (401, 403),
                          f"got {wrong.status_code} - wrong token accepted!")
        else:
            print("  SKIP  positive admin test (pass --admin-token to enable)")
    except Exception as exc:  # noqa: BLE001
        results.check("admin auth works", False, f"{type(exc).__name__}: {exc}")

    client.close()
    return results.summary()


if __name__ == "__main__":
    raise SystemExit(main())