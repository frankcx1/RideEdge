from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from farol import collect, course, here, history


PACIFIC = ZoneInfo("America/Los_Angeles")


def test_round7_sparse_archive_now_and_plan_both_hold() -> None:
    """R6-01: Two paid-trip archive records ($42/hr) must not trigger a MOVE in either Now or Plan."""
    now_local = datetime(2026, 10, 23, 7, 30, tzinfo=PACIFIC)
    rows = [
        {
            "zone": "woodinville_wine",
            "hour": h,
            "sample_trips": 2,
            "historical_net_per_hour": 42.0,
            "score": 42.0,
            "thin": True,
            "grain": "zone",
            "reposition_minutes": 10,
            "reposition_miles": 4,
        }
        for h in range(24)
    ] + [
        {
            "zone": "totem_lake",
            "hour": h,
            "sample_trips": 0,
            "score": 0.0,
            "thin": True,
            "grain": "none",
            "reposition_minutes": 0,
            "reposition_miles": 0,
        }
        for h in range(24)
    ]

    with ExitStack() as stack:
        for name, value in [
            ("_read_json", {}),
            ("seatac_6h_forecast", {"hours": []}),
            ("load_observed_trips", []),
            ("load_anchors", []),
            ("nearby_train_stations", []),
            ("feed_health_view", {}),
        ]:
            stack.enter_context(patch.object(course, name, return_value=value))
        stack.enter_context(patch.object(history, "summarize_zone_outcomes", return_value={}))
        stack.enter_context(patch.object(course, "sit_here", return_value={"all_rows": rows, "ranked": rows}))

        p = course.build_6h_shift_course(
            origin_area="totem_lake",
            now=now_local,
            pull_all=False,
            minutes_available=360,
            reposition_under_minutes=15,
        )
        nowrows = [r for r in rows if r["hour"] == now_local.hour]
        place = here.resolve("totem_lake")
        action, _, _ = here._pick_action(place, nowrows, [], current=now_local, max_reposition_minutes=15)

    assert action == "WATCH"
    first_stop = p["stops"][0]
    assert first_stop["zone"] == "totem_lake"
    assert first_stop["action"] == "WATCH"
    assert first_stop["decision_state"] == "WATCH"
    assert "Move to Woodinville" not in p["action_plan"]["immediate_move"]


def test_round7_calibrated_archive_now_and_plan_both_move() -> None:
    """R6-01: When origin and destination both have calibrated zone_hour_weekday history and a clear net advantage, Now and Plan agree on MOVE."""
    now_local = datetime(2026, 10, 23, 7, 30, tzinfo=PACIFIC)
    rows = [
        {
            "zone": "redmond_downtown",
            "hour": h,
            "sample_trips": 6,
            "historical_net_per_hour": 46.0,
            "score": 82.0,
            "thin": False,
            "grain": "zone_hour_weekday",
            "reposition_minutes": 10,
            "reposition_miles": 4.2,
        }
        for h in range(24)
    ] + [
        {
            "zone": "totem_lake",
            "hour": h,
            "sample_trips": 4,
            "historical_net_per_hour": 22.0,
            "score": 48.0,
            "thin": False,
            "grain": "zone_hour_weekday",
            "reposition_minutes": 0,
            "reposition_miles": 0.0,
        }
        for h in range(24)
    ]

    with ExitStack() as stack:
        for name, value in [
            ("_read_json", {}),
            ("seatac_6h_forecast", {"hours": []}),
            ("load_observed_trips", []),
            ("load_anchors", []),
            ("nearby_train_stations", []),
            ("feed_health_view", {}),
        ]:
            stack.enter_context(patch.object(course, name, return_value=value))
        stack.enter_context(patch.object(history, "summarize_zone_outcomes", return_value={}))
        stack.enter_context(patch.object(course, "sit_here", return_value={"all_rows": rows, "ranked": rows}))

        p = course.build_6h_shift_course(
            origin_area="totem_lake",
            now=now_local,
            pull_all=False,
            minutes_available=360,
            reposition_under_minutes=20,
        )
        nowrows = [r for r in rows if r["hour"] == now_local.hour]
        place = here.resolve("totem_lake")
        action, _, best = here._pick_action(place, nowrows, [], current=now_local, max_reposition_minutes=20)

    assert action == "MOVE"
    assert best is not None and best["zone"] == "redmond_downtown"
    first_stop = p["stops"][0]
    assert first_stop["zone"] == "redmond_downtown"
    assert first_stop["decision_state"] == "MOVE"


def test_round7_home_and_positioned_hub_now_plan_agreement() -> None:
    """R6-01: Residential Home start and positioned pickup center preserve positioning semantics across Now and Plan."""
    now_local = datetime(2026, 10, 23, 7, 30, tzinfo=PACIFIC)
    rows = [
        {
            "zone": "totem_lake",
            "hour": h,
            "sample_trips": 0,
            "score": 0.0,
            "thin": True,
            "grain": "none",
            "reposition_minutes": 0,
            "reposition_miles": 0,
        }
        for h in range(24)
    ]

    with ExitStack() as stack:
        for name, value in [
            ("_read_json", {}),
            ("seatac_6h_forecast", {"hours": []}),
            ("load_observed_trips", []),
            ("load_anchors", []),
            ("nearby_train_stations", []),
            ("feed_health_view", {}),
        ]:
            stack.enter_context(patch.object(course, name, return_value=value))
        stack.enter_context(patch.object(history, "summarize_zone_outcomes", return_value={}))
        stack.enter_context(patch.object(course, "sit_here", return_value={"all_rows": rows, "ranked": rows}))

        home_course = course.build_6h_shift_course(
            origin_area="Home",
            now=now_local,
            pull_all=False,
            minutes_available=360,
            reposition_under_minutes=15,
        )
        home_place = here.resolve("Home")
        home_action, _, _ = here._pick_action(home_place, [rows[7]], [], current=now_local, max_reposition_minutes=15)

        hub_course = course.build_6h_shift_course(
            origin_area="Village at Totem Lake",
            now=now_local,
            pull_all=False,
            minutes_available=360,
            reposition_under_minutes=15,
        )
        hub_place = here.resolve("Village at Totem Lake")
        hub_action, _, _ = here._pick_action(hub_place, [rows[7]], [], current=now_local, max_reposition_minutes=15)

    assert home_action == "MOVE"
    assert home_course["stops"][0]["recommendation_basis"] == "positioning_heuristic"
    assert home_course["stops"][0]["decision_state"] == "MOVE"
    assert "unverified" in home_course["stops"][0]["primary_trigger"].lower()

    assert hub_action == "WAIT"
    assert hub_course["stops"][0]["recommendation_basis"] == "positioned_pickup_center"
    assert hub_course["stops"][0]["action"] == "WAIT"
    assert hub_course["stops"][0]["decision_state"] == "STAY"


def test_round7_full_360_minute_shift_across_offsets_midnight_and_dst() -> None:
    """R6-02: 360-minute shift course covers the full 360 elapsed minutes across :00, :30, :45, :50, midnight, and DST."""
    rows = [
        {
            "zone": "totem_lake",
            "hour": h,
            "sample_trips": 0,
            "score": 0.0,
            "thin": True,
            "grain": "none",
            "reposition_minutes": 0,
            "reposition_miles": 0,
        }
        for h in range(24)
    ]
    starts = [
        datetime(2026, 10, 23, 7, 0, tzinfo=PACIFIC),
        datetime(2026, 10, 23, 7, 30, tzinfo=PACIFIC),
        datetime(2026, 10, 23, 7, 45, tzinfo=PACIFIC),
        datetime(2026, 10, 23, 7, 50, tzinfo=PACIFIC),
        datetime(2026, 10, 23, 21, 30, tzinfo=PACIFIC),
        datetime(2026, 11, 1, 0, 30, tzinfo=PACIFIC),
    ]
    with ExitStack() as stack:
        for name, value in [
            ("_read_json", {}),
            ("seatac_6h_forecast", {"hours": []}),
            ("load_observed_trips", []),
            ("load_anchors", []),
            ("nearby_train_stations", []),
            ("feed_health_view", {}),
        ]:
            stack.enter_context(patch.object(course, name, return_value=value))
        stack.enter_context(patch.object(history, "summarize_zone_outcomes", return_value={}))
        stack.enter_context(patch.object(course, "sit_here", return_value={"all_rows": rows, "ranked": rows}))

        for start_dt in starts:
            res = course.build_6h_shift_course(
                origin_area="totem_lake",
                now=start_dt,
                pull_all=False,
                minutes_available=None,
                reposition_under_minutes=15,
            )
            assert res["constraints_applied"]["minutes_available"] == 360
            stops = res["stops"]
            last_end = datetime.fromisoformat(stops[-1]["ends_at"])
            elapsed_min = round((last_end - start_dt).total_seconds() / 60.0, 1)
            assert elapsed_min == 360.0, f"Expected 360.0 min for {start_dt.isoformat()}, got {elapsed_min}"


def test_round7_source_coverage_inventory_covers_all_23_adapters() -> None:
    """Priority 3: build_source_coverage_inventory returns a 23-adapter source_coverage accounting."""
    inv = collect.build_source_coverage_inventory(health={"feeds": []})
    assert len(inv) == 23
    for row in inv:
        assert row["adapter"]
        assert row["role_in_decision"]
        assert row["freshness_rule"]
        assert isinstance(row["influenced_decision"], bool)
        if not row["influenced_decision"]:
            assert row["exclusion_reason"]
