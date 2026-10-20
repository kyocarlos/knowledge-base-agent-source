import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("wifi8_quality_schedule", Path(__file__).resolve().parent.parent / "scripts" / "wifi8_quality_schedule.py")
sched = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sched)

TZ = "Asia/Taipei"  # UTC+8, no daylight saving
CONFIG = {"zones": {"test": {}, "da40": {}}}


def utc(hhmm_taipei, day=20):
    """2026-10-20 is a Tuesday, 2026-10-25 a Sunday."""
    h, m = map(int, hhmm_taipei.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)


def local(hhmm, day=20):
    return utc(hhmm, day).astimezone(sched.ZoneInfo(TZ))


@pytest.mark.parametrize("now,expected", [("03:29", False), ("03:30", True), ("05:00", True), ("06:29", True), ("06:30", False), ("23:00", False)])
def test_due_from_the_chosen_time_until_the_catch_up_window_ends(now, expected):
    assert sched.due(local(now), "03:30", None, 180) is expected


def test_due_once_per_local_date_and_never_for_a_malformed_time():
    assert sched.due(local("04:00"), "03:30", "2026-10-20", 180) is False
    assert sched.due(local("04:00"), "03:30", "2026-10-19", 180) is True
    for bad in ("3:30", "24:00", "03:60", "", None, "abc"):
        assert sched.due(local("04:00"), bad, None, 180) is False


def test_the_default_time_applies_when_a_zone_has_no_setting_or_a_broken_one():
    assert [d["zone"] for d in sched.due_zones(CONFIG, lambda z: None, utc("03:35"), {})] == ["test", "da40"]
    assert [d["zone"] for d in sched.due_zones(CONFIG, lambda z: {"time": "25:99"}, utc("03:35"), {})] == ["test", "da40"]
    assert sched.due_zones(CONFIG, lambda z: None, utc("03:25"), {}) == []


def test_each_zone_runs_at_its_own_chosen_time():
    settings = {"test": {"time": "21:00", "timezone": TZ}, "da40": {"time": "07:15", "timezone": TZ}}
    assert sched.due_zones(CONFIG, settings.get, utc("07:20"), {}) == [{"zone": "da40", "levels": "retrieval,trust", "date": "2026-10-20", "time": "07:15"}]
    assert [d["zone"] for d in sched.due_zones(CONFIG, settings.get, utc("21:05"), {})] == ["test"]
    assert sched.due_zones(CONFIG, settings.get, utc("12:00"), {}) == []


def test_weekdays_run_the_daily_levels_and_the_weekly_day_runs_everything():
    weekday = sched.due_zones(CONFIG, lambda z: None, utc("03:35", day=20), {})
    sunday = sched.due_zones(CONFIG, lambda z: None, utc("03:35", day=25), {})
    assert {d["levels"] for d in weekday} == {"retrieval,trust"}
    assert {d["levels"] for d in sunday} == {"retrieval,agent,trust"}


def test_a_zone_that_already_ran_today_is_not_due_again_but_is_tomorrow():
    state = {}
    item = sched.due_zones(CONFIG, lambda z: None, utc("03:35"), state)[0]
    sched.record_run(state, item, utc("03:36"))
    assert all(d["zone"] != item["zone"] for d in sched.due_zones(CONFIG, lambda z: None, utc("03:40"), state))
    assert any(d["zone"] == item["zone"] for d in sched.due_zones(CONFIG, lambda z: None, utc("03:35", day=21), state))


def test_timezone_follows_the_zone_and_an_unknown_name_falls_back():
    settings = {"test": {"time": "03:30", "timezone": "UTC"}}  # 03:30 UTC is 11:30 in Taipei
    assert sched.due_zones({"zones": {"test": {}}}, settings.get, utc("11:35"), {})
    assert not sched.due_zones({"zones": {"test": {}}}, settings.get, utc("03:35"), {})
    _, name = sched.local_now(utc("03:35"), "No/Such_Zone", TZ)
    assert name == TZ


def test_failures_are_retried_a_few_times_then_given_up_for_that_date_only():
    state = {}
    item = {"zone": "test", "levels": "retrieval,trust", "date": "2026-10-20", "time": "03:30"}
    assert [sched.record_failure(state, item, 3) for _ in range(3)] == [1, 2, 3]
    assert sched.due_zones({"zones": {"test": {}}}, lambda z: None, utc("04:00"), state) == []  # gave up for today
    assert sched.due_zones({"zones": {"test": {}}}, lambda z: None, utc("03:35", day=21), state)  # tomorrow starts fresh
    assert sched.record_failure(state, {**item, "date": "2026-10-21"}, 3) == 1


def test_one_unreadable_zone_does_not_hide_the_others():
    def read(zone):
        if zone == "test":
            raise OSError("docker exec failed")
        return {"time": "03:30", "timezone": TZ}

    assert [d["zone"] for d in sched.due_zones(CONFIG, read, utc("03:40"), {})] == ["da40"]


def test_state_survives_a_round_trip_and_a_corrupt_file_reads_as_empty(tmp_path):
    path = tmp_path / "state.json"
    assert sched.load_state(path) == {}
    path.write_text("{not json")
    assert sched.load_state(path) == {}
    state = {}
    sched.record_run(state, {"zone": "da40", "levels": "retrieval,trust", "date": "2026-10-20", "time": "03:30"}, utc("03:36"))
    sched.save_state(path, state)
    assert sched.load_state(path)["da40"]["last_run_date"] == "2026-10-20"
