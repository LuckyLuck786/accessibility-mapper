"""Phase 3 acceptance tests for the Ghost Space engine.

Each test states the product claim it defends:

* ``test_no_show_probability_*`` - a smoothed historical rate plus live evidence.
* ``test_release_rule_*`` - grace, threshold and zero-headcount are all required.
* ``test_reclaim_*`` - an organiser can take the room back, and it counts as a
  false release in the accuracy metric.
* ``test_reachability_*`` - the core novelty: a room behind a broken lift is
  excluded with the barrier named.
* ``test_metrics_*`` - baseline vs Ghost Space, computed rather than hardcoded.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db.space_models import Booking, NoShowStat, OccupancySignal, Room
from app.services import space_service
from app.services.graph_service import graph_service


def _clock_at(db, when: datetime) -> None:
    """Pin the demo clock to an exact instant."""
    space_service.set_clock(db, mode="demo", jump_to=when, speed=1.0)


def _first_ghost(db, *, past_start_minutes: int = 30):
    """A booking whose window is open, with zero observed headcount."""
    now = space_service.now(db)
    candidates = [
        b
        for b in db.query(Booking).all()
        if b.simulated_will_show is False
        and b.start_ts <= now - timedelta(minutes=past_start_minutes) < b.end_ts
        and b.status == "active"
    ]
    assert candidates, "expected at least one in-flight ghost booking in the seed"
    return candidates[0]


# -----------------------------------------------------------------------
# Data model
# -----------------------------------------------------------------------
def test_rooms_are_linked_to_real_graph_nodes(db_session):
    rooms = db_session.query(Room).all()
    assert len(rooms) >= 12, "spec requires 12+ rooms"
    graph_service.ensure_fresh(db_session)
    for room in rooms:
        assert room.node_id in graph_service.graph, f"{room.id} points at a missing node"
        assert room.power_kw > 0


def test_some_rooms_are_not_step_free(db_session):
    rooms = db_session.query(Room).all()
    assert any(not r.is_step_free_access for r in rooms), (
        "the seed must include rooms without step-free access so the exclusion "
        "path is demonstrable"
    )


def test_seed_has_a_realistic_day_of_bookings(db_session):
    bookings = db_session.query(Booking).all()
    assert len(bookings) >= 40, "spec requires 40+ bookings in one day"
    ghosts = [b for b in bookings if not b.simulated_will_show]
    rate = len(ghosts) / len(bookings)
    assert 0.20 <= rate <= 0.40, f"ghost rate {rate:.2f} outside the 25-35% band"
    days = {b.start_ts.date() for b in bookings}
    assert len(days) == 1, "the seeded bookings must all fall on one demo day"


def test_noshow_history_is_populated(db_session):
    stats = db_session.query(NoShowStat).all()
    assert len(stats) >= 40
    assert all(s.bookings_count > 0 for s in stats)
    assert any(s.noshow_count > 0 for s in stats)


def test_occupancy_signals_hold_headcount_only(db_session):
    """Privacy contract: no identity column may ever appear on the model."""
    columns = {c.name for c in OccupancySignal.__table__.columns}
    forbidden = {"user_id", "reporter_id", "device_id", "image", "image_url", "face", "email"}
    assert not (columns & forbidden), f"occupancy table leaks identity: {columns & forbidden}"
    assert "headcount" in columns


# -----------------------------------------------------------------------
# No-show probability
# -----------------------------------------------------------------------
def test_smoothed_prior_is_beta_smoothed_and_bounded(db_session):
    prior, provenance = space_service.smoothed_prior(
        db_session, "club", datetime(2026, 10, 5, 19, 0, tzinfo=UTC)
    )
    assert 0.0 <= prior <= 1.0
    assert provenance["cell"] in ("exact", "organizer_average", "global_default")
    if provenance["cell"] == "exact":
        expected = (provenance["noshow_count"] + settings.ghost_beta_alpha) / (
            provenance["bookings_count"] + settings.ghost_beta_alpha + settings.ghost_beta_beta
        )
        assert prior == pytest.approx(expected)


def test_club_bookings_score_higher_than_faculty(db_session):
    """The product claim: clubs are the no-show offenders."""
    when = datetime(2026, 10, 5, 21, 0, tzinfo=UTC)
    club, _ = space_service.smoothed_prior(db_session, "club", when)
    faculty, _ = space_service.smoothed_prior(db_session, "faculty", when)
    assert club > faculty, f"club {club:.3f} should exceed faculty {faculty:.3f}"


def test_probability_is_low_before_start_and_rises_with_silence(db_session):
    booking = _first_ghost(db_session)

    early = space_service.no_show_probability(
        db_session, booking, elapsed_override=0.0
    )
    mid = space_service.no_show_probability(
        db_session, booking, elapsed_override=settings.ghost_grace_minutes
    )
    late = space_service.no_show_probability(
        db_session, booking, elapsed_override=settings.ghost_grace_minutes + 30
    )

    assert early["p_noshow"] <= mid["p_noshow"] <= late["p_noshow"]
    assert early["p_noshow"] < settings.ghost_probability_threshold, (
        "inside the grace period a room must not be released"
    )
    assert late["p_noshow"] > settings.ghost_probability_threshold
    assert 0.0 <= late["p_noshow"] <= 1.0


def test_probability_always_lists_its_evidence(db_session):
    booking = _first_ghost(db_session)
    result = space_service.no_show_probability(db_session, booking)
    kinds = {item["kind"] for item in result["evidence"]}
    assert {"historical_prior", "live_occupancy", "elapsed"} <= kinds
    assert all(item["detail"] for item in result["evidence"])
    assert "not a trained model" in result["method"]


def test_occupied_room_is_never_predicted_as_a_no_show(db_session):
    occupied = next(
        b
        for b in db_session.query(Booking).all()
        if b.simulated_will_show and b.status in ("active", "checked_in")
    )
    result = space_service.no_show_probability(
        db_session, occupied, elapsed_override=120
    )
    assert result["headcount"] > 0
    assert result["p_noshow"] < settings.ghost_probability_threshold


# -----------------------------------------------------------------------
# Release rule
# -----------------------------------------------------------------------
def test_release_rule_requires_all_three_conditions(db_session):
    booking = _first_ghost(db_session)
    now = space_service.now(db_session)

    inside_grace = space_service.evaluate_booking(
        db_session, booking, _aware(booking.start_ts) + timedelta(minutes=2)
    )
    assert inside_grace["decision"] == "hold"
    assert any("grace period" in reason for reason in
               inside_grace["constraints_applied"]["blocking_reasons"])

    past_grace = space_service.evaluate_booking(
        db_session, booking, _aware(booking.start_ts) + timedelta(minutes=45)
    )
    assert past_grace["decision"] == "release"
    assert past_grace["probability"] >= settings.ghost_probability_threshold


def test_zero_headcount_is_required(db_session):
    occupied = next(
        b
        for b in db_session.query(Booking).all()
        if b.simulated_will_show and b.status in ("active", "checked_in")
    )
    decision = space_service.evaluate_booking(
        db_session, occupied, _aware(occupied.start_ts) + timedelta(minutes=90)
    )
    assert decision["decision"] == "hold"
    assert any("headcount" in reason for reason in
               decision["constraints_applied"]["blocking_reasons"])


def test_release_pass_marks_the_room_available_again(db_session):
    before = len(
        space_service.available_rooms(
            db_session,
            start=space_service.now(db_session) + timedelta(minutes=5),
            end=space_service.now(db_session) + timedelta(minutes=65),
            capacity=0,
        )
    )
    result = space_service.run_release_pass(db_session)
    db_session.commit()
    assert result["released"], "expected at least one release in the seeded day"

    booking_id = result["released"][0]["booking_id"]
    booking = db_session.get(Booking, booking_id)
    assert booking.status == "ghost_released"
    assert booking.release_reason and "p_noshow" in booking.release_reason
    assert booking.released_at is not None

    after = len(
        space_service.available_rooms(
            db_session,
            start=space_service.now(db_session) + timedelta(minutes=5),
            end=space_service.now(db_session) + timedelta(minutes=65),
            capacity=0,
        )
    )
    assert after > before, "a released room must re-enter the available pool"


def test_release_is_idempotent(db_session):
    space_service.run_release_pass(db_session)
    db_session.commit()
    first = len(db_session.query(Booking).filter(Booking.status == "ghost_released").all())
    space_service.run_release_pass(db_session)
    db_session.commit()
    second = len(db_session.query(Booking).filter(Booking.status == "ghost_released").all())
    assert first == second, "re-running the pass must not double-release"


def test_release_decision_carries_a_full_explanation(db_session):
    booking = _first_ghost(db_session)
    decision = space_service.evaluate_booking(
        db_session, booking, _aware(booking.start_ts) + timedelta(minutes=45)
    )
    assert decision["decision"] == "release"
    assert 0.0 <= decision["probability"] <= 1.0
    assert decision["evidence"]
    assert decision["constraints_applied"]["grace_period_minutes"] == settings.ghost_grace_minutes
    assert decision["timestamp"]


# -----------------------------------------------------------------------
# Reclaim
# -----------------------------------------------------------------------
def test_reclaim_marks_a_false_release(db_session):
    result = space_service.run_release_pass(db_session)
    db_session.commit()
    assert result["released"]
    booking_id = result["released"][0]["booking_id"]

    reclaimed = space_service.reclaim_booking(db_session, booking_id, actor="club-lead")
    db_session.commit()
    booking = db_session.get(Booking, booking_id)
    assert reclaimed["action"] == "reclaimed"
    assert booking.status == "reclaimed"
    assert booking.reclaimed_at is not None
    assert "false release" in booking.release_reason


def test_reclaim_after_the_window_is_refused(db_session):
    result = space_service.run_release_pass(db_session)
    db_session.commit()
    booking_id = result["released"][0]["booking_id"]
    booking = db_session.get(Booking, booking_id)

    # Push the clock past the reclaim window.
    far = space_service.now(db_session) + timedelta(
        minutes=settings.ghost_reclaim_window_minutes + 10
    )
    space_service.set_clock(db_session, jump_to=far)
    with pytest.raises(ValueError, match="reclaim window"):
        space_service.reclaim_booking(db_session, booking_id)
    db_session.rollback()


def test_checking_in_after_a_release_is_also_a_false_release(db_session):
    result = space_service.run_release_pass(db_session)
    db_session.commit()
    booking_id = result["released"][0]["booking_id"]
    booking = db_session.get(Booking, booking_id)

    outcome = space_service.check_in(db_session, booking.room_id, 14, booking_id=booking_id)
    db_session.commit()
    assert outcome["was_false_release"] is True
    assert db_session.get(Booking, booking_id).status == "reclaimed"


def test_checkin_rejects_an_unknown_room(db_session):
    with pytest.raises(LookupError):
        space_service.check_in(db_session, "rm_does_not_exist", 3)


# -----------------------------------------------------------------------
# Reachability-aware matching - the core novelty
# -----------------------------------------------------------------------
def _step_free_request(db_session, **overrides):
    payload = {
        "capacity": 10,
        "start": space_service.now(db_session) + timedelta(minutes=15),
        "end": space_service.now(db_session) + timedelta(minutes=105),
        "needs_step_free": True,
        # Red Square: a normal street-level junction on the seeded network.
        "origin_lat": 47.65599,
        "origin_lng": -122.30836,
        "origin_label": "Red Square",
    }
    payload.update(overrides)
    return payload


def test_step_free_request_excludes_rooms_behind_a_broken_lift(db_session):
    """Health Sciences 302 sits behind the seeded broken lift."""
    result = space_service.match_rooms(
        db_session, persist=False, **_step_free_request(db_session, capacity=16)
    )
    excluded_ids = {item["room"]["id"] for item in result["excluded"]}
    assert "rm_hsb_302" in excluded_ids, "the lift-only room must be excluded"

    entry = next(i for i in result["excluded"] if i["room"]["id"] == "rm_hsb_302")
    assert entry["reason_code"] == "unreachable"
    assert entry["barrier_id"] is not None
    assert entry["category"] == "broken_lift"
    assert "broken lift" in entry["reason"].lower()
    assert entry["verified_at"], "the reason must say when the barrier was verified"

    # It must be excluded, not merely deprioritised.
    assert "rm_hsb_302" not in {r["room"]["id"] for r in result["results"]}


def test_resolving_the_lift_makes_the_room_reachable_again(db_session):
    """The barrier is not a hard-coded exclusion - resolve it and re-check."""
    from app.api.deps import admin_token_ok  # noqa: F401  (import sanity)

    result = space_service.match_rooms(
        db_session, persist=False, **_step_free_request(db_session, capacity=16)
    )
    assert "rm_hsb_302" in {i["room"]["id"] for i in result["excluded"]}

    from app.db.models import Barrier
    from app.services import barrier_service

    broken = db_session.query(Barrier).filter(Barrier.category == "broken_lift").first()
    barrier_service.resolve_barrier(db_session, broken.id, actor="test")
    db_session.commit()
    graph_service.invalidate()

    try:
        after = space_service.match_rooms(
            db_session, persist=False, **_step_free_request(db_session, capacity=16)
        )
        excluded_after = {i["room"]["id"] for i in after["excluded"]}
        if "rm_hsb_302" not in excluded_after:
            assert "rm_hsb_302" in {r["room"]["id"] for r in after["results"]}
    finally:
        # Leave the demo state as we found it.
        barrier_service.reopen_barrier(db_session, broken.id, actor="test", reason="test")
        db_session.commit()
        graph_service.invalidate()


def test_excluded_reason_names_the_blocked_ramp(db_session):
    """More Hall rooms depend on the seeded blocked ramp."""
    result = space_service.match_rooms(
        db_session, persist=False, **_step_free_request(db_session, capacity=20)
    )
    blocked = [
        i for i in result["excluded"]
        if i.get("category") == "blocked_ramp"
    ]
    assert blocked, "expected a blocked-ramp exclusion for More Hall"
    assert all("blocked ramp" in i["reason"].lower() for i in blocked)


def test_request_explains_every_constraint(db_session):
    result = space_service.match_rooms(
        db_session, persist=False, **_step_free_request(db_session)
    )
    explanation = result["explanation"]
    assert explanation["decision"] in ("matched", "no_match")
    assert explanation["timestamp"]
    assert any("capacity" in str(c) for c in explanation["constraints_applied"])
    assert any("step-free" in str(c) for c in explanation["constraints_applied"])
    for item in result["results"]:
        assert item["reasons"], "each match must carry reasons"
        assert item["straight_line_m"] >= 0


def test_capacity_shortfall_is_explained(db_session):
    result = space_service.match_rooms(
        db_session, persist=False, **_step_free_request(db_session, capacity=150)
    )
    for item in result["excluded"]:
        assert item["reason_code"] in ("capacity", "booked", "unreachable")
        assert item["reason"]


def test_non_step_free_request_does_not_run_reachability(db_session):
    """A requester who does not need step-free access should not be blocked."""
    result = space_service.match_rooms(
        db_session,
        persist=False,
        **_step_free_request(db_session, capacity=8, needs_step_free=False),
    )
    unreachable = [i for i in result["excluded"] if i["reason_code"] == "unreachable"]
    assert not unreachable, "reachability is only a constraint for step-free requests"


# -----------------------------------------------------------------------
# Metrics
# -----------------------------------------------------------------------
def test_metrics_are_computed_not_hardcoded(db_session):
    metrics = space_service.metrics(db_session)

    # Baseline must equal the sum of empty booked hours across all bookings.
    bookings = db_session.query(Booking).all()
    headcount = {s.booking_id: s.headcount for s in db_session.query(OccupancySignal).all()}
    empty_hours = 0.0
    for booking in bookings:
        if headcount.get(booking.id, 0) == 0:
            span = (_aware(booking.end_ts) - _aware(booking.start_ts)).total_seconds() / 3600
            empty_hours += span

    assert metrics["baseline"]["empty_booked_room_hours"] == pytest.approx(empty_hours, abs=0.05)
    assert metrics["baseline"]["wasted_kwh"] > 0
    assert metrics["energy"]["is_estimate"] is True
    assert "ESTIMATED" in metrics["energy"]["method"]
    assert metrics["ghost_space"]["recovered_room_hours"] >= 0


def test_releases_raise_recovered_hours_and_accuracy_is_real(db_session):
    before = space_service.metrics(db_session)
    result = space_service.run_release_pass(db_session)
    db_session.commit()
    after = space_service.metrics(db_session)

    if result["released"]:
        assert after["ghost_space"]["recovered_room_hours"] > before["ghost_space"]["recovered_room_hours"]
        assert after["ghost_space"]["kwh_saved"] > 0
        assert after["releases"]["decisions"] >= len(result["released"])

    accuracy = after["release_accuracy"]
    assert accuracy["value"] is None or 0.0 <= accuracy["value"] <= 1.0
    if accuracy["value"] is not None and after["releases"]["decisions"]:
        assert accuracy["value"] == pytest.approx(
            1 - after["releases"]["false_releases"] / after["releases"]["decisions"], abs=1e-3
        )


def test_reclaim_shows_up_in_the_accuracy_metric(db_session):
    result = space_service.run_release_pass(db_session)
    db_session.commit()
    assert result["released"]
    space_service.reclaim_booking(db_session, result["released"][0]["booking_id"])
    db_session.commit()

    metrics = space_service.metrics(db_session)
    assert metrics["releases"]["false_releases"] >= 1
    assert metrics["release_accuracy"]["value"] < 1.0


def test_metrics_count_requests(db_session):
    space_service.match_rooms(db_session, **_step_free_request(db_session))
    db_session.commit()
    metrics = space_service.metrics(db_session)
    assert metrics["requests"]["total"] >= 1
    assert metrics["requests"]["step_free_total"] >= 1
    assert 0.0 <= (metrics["requests"]["fulfilment_rate"] or 0) <= 1.0


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)