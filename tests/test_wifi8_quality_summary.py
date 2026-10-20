import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("wifi8_quality_summary", Path(__file__).resolve().parent.parent / "scripts" / "wifi8_quality_summary.py")
summary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(summary)

TZ = "Asia/Taipei"  # UTC+8, no daylight saving
CONFIG = {"zones": {"test": {}, "da40": {}}}


def utc(hhmm_taipei, day=21):
    h, m = map(int, hhmm_taipei.split(":"))
    return datetime(2026, 10, day, h, m, tzinfo=timezone(timedelta(hours=8))).astimezone(timezone.utc)


def row(zone, level, ts_utc, status="PASS", metrics=None, run="20261021T000000Z", package="wifi8-p"):
    return {"ts": ts_utc.isoformat(timespec="seconds"), "run": run, "zone": zone, "level": level, "status": status,
            "metrics": metrics or {}, "package_id": package}


@pytest.fixture
def history(tmp_path):
    rows = [row("da40", "retrieval", utc("03:30"), metrics={"hit_at_10": 0.9189, "mrr": 0.7711}),
            row("da40", "trust", utc("03:30"), status="INSUFFICIENT", metrics={"answers": 1}),
            row("da40", "agent", utc("04:00", day=18), metrics={"answer_pass": 0.925}),
            row("test", "retrieval", utc("03:30"), metrics={"hit_at_10": 0.9, "mrr": 0.7})]
    path = tmp_path / "history.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + "{not json\n", encoding="utf-8")
    return path


@pytest.mark.parametrize("now,expected", [("08:59", False), ("09:00", True), ("11:59", True), ("12:00", False), ("23:30", False)])
def test_due_only_from_the_chosen_time_until_the_catch_up_window_ends(now, expected):
    local = utc(now).astimezone(summary.ZoneInfo(TZ))
    assert summary.due(local, "09:00", None, 180) is expected


def test_due_once_per_local_date_and_never_for_a_malformed_time():
    local = utc("10:00").astimezone(summary.ZoneInfo(TZ))
    assert summary.due(local, "09:00", "2026-10-21", 180) is False
    assert summary.due(local, "09:00", "2026-10-20", 180) is True
    for bad in ("9:00", "24:00", "09:60", "", None, "abc"):
        assert summary.due(local, bad, None, 180) is False


def test_the_date_and_time_follow_the_zones_own_timezone():
    now = datetime(2026, 10, 21, 1, 30, tzinfo=timezone.utc)  # 09:30 in Taipei, 01:30 in UTC
    taipei, _ = summary.local_now(now, "Asia/Taipei", "UTC")
    assert taipei.hour == 9 and summary.due(taipei, "09:00", None, 180)
    unknown, name = summary.local_now(now, "No/Such_Zone", "Asia/Taipei")
    assert name == "Asia/Taipei" and unknown.hour == 9  # an unknown name falls back to the default


def test_the_message_lists_each_level_with_numbers_and_flags_what_is_overdue(history, tmp_path):
    now_local = utc("09:00").astimezone(summary.ZoneInfo(TZ))
    text = summary.build_summary("da40", summary.latest_rows(history, "da40"), now_local, TZ, summary.DEFAULTS["stale_hours"], tmp_path)
    assert "每日摘要・DA40" in text and "2026-10-21 09:00（Asia/Taipei）" in text
    assert "①檢索：PASS（命中@10 91.9%、MRR 0.7711）・10/21 03:30" in text
    assert "③可信度：INSUFFICIENT（最近 24 小時 1 則回答）" in text
    assert "②Agent：PASS（答案通過 92.5%）・10/18 04:00" in text and "超時未更新" not in text  # 3 days old, the weekly limit is 8 days
    assert "⚠" not in text and f"報告：{tmp_path / '20261021T000000Z' / 'report.md'}" in text


def test_a_level_without_any_record_and_an_old_one_are_called_out(history, tmp_path):
    now_local = utc("09:00", day=25).astimezone(summary.ZoneInfo(TZ))
    text = summary.build_summary("test", summary.latest_rows(history, "test"), now_local, TZ, summary.DEFAULTS["stale_hours"], tmp_path)
    assert "②Agent：尚無檢查紀錄" in text and "③可信度：尚無檢查紀錄" in text
    assert "（超時未更新）" in text and "⚠" in text and "排程可能沒有執行" in text


def test_send_due_sends_once_a_day_only_for_zones_that_asked(history, tmp_path):
    sent_texts, state = [], tmp_path / "summary-state.json"
    settings = {"da40": {"enabled": True, "time": "09:00", "timezone": TZ}, "test": {"enabled": False, "time": "09:00"}}
    send = lambda text: sent_texts.append(text)  # noqa: E731
    read = lambda zone: settings.get(zone)  # noqa: E731
    assert summary.send_due(CONFIG, read, utc("08:55"), history, state, tmp_path, send) == []
    assert summary.send_due(CONFIG, read, utc("09:05"), history, state, tmp_path, send) == ["da40"]
    assert len(sent_texts) == 1 and "DA40" in sent_texts[0] and "TEST" not in sent_texts[0]
    assert summary.send_due(CONFIG, read, utc("09:10"), history, state, tmp_path, send) == []  # already sent for this date
    assert json.loads(state.read_text())["da40"]["last_sent_date"] == "2026-10-21"
    assert summary.send_due(CONFIG, read, utc("09:05", day=22), history, state, tmp_path, send) == ["da40"]  # next day again


def test_each_zone_uses_its_own_time(history, tmp_path):
    sent = []
    settings = {"da40": {"enabled": True, "time": "07:30", "timezone": TZ}, "test": {"enabled": True, "time": "18:45", "timezone": TZ}}
    state = tmp_path / "s.json"
    assert summary.send_due(CONFIG, settings.get, utc("07:35"), history, state, tmp_path, sent.append) == ["da40"]
    assert summary.send_due(CONFIG, settings.get, utc("18:50"), history, state, tmp_path, sent.append) == ["test"]
    assert len(sent) == 2


def test_a_failed_send_is_retried_at_the_next_poll_and_does_not_block_other_zones(history, tmp_path):
    calls, state = [], tmp_path / "s.json"
    settings = {z: {"enabled": True, "time": "09:00", "timezone": TZ} for z in ("da40", "test")}

    def flaky(text):
        calls.append(text)
        if "DA40" in text and len([c for c in calls if "DA40" in c]) == 1:
            raise OSError("telegram down")

    assert summary.send_due(CONFIG, settings.get, utc("09:02"), history, state, tmp_path, flaky) == ["test"]
    assert summary.send_due(CONFIG, settings.get, utc("09:07"), history, state, tmp_path, flaky) == ["da40"]


def test_a_missing_or_unreadable_setting_means_no_message_and_a_broken_one_does_not_stop_the_rest(history, tmp_path):
    def read(zone):
        if zone == "test":
            raise OSError("docker exec failed")
        return {"enabled": "yes", "time": "09:00"}  # only a real true counts

    assert summary.send_due(CONFIG, read, utc("09:05"), history, tmp_path / "s.json", tmp_path, lambda text: None) == []
    assert summary.send_due(CONFIG, lambda z: None, utc("09:05"), history, tmp_path / "s.json", tmp_path, lambda text: None) == []


def test_a_zone_without_a_valid_time_uses_the_default_time(history, tmp_path):
    sent = []
    settings = {"da40": {"enabled": True, "time": "25:99", "timezone": TZ}}
    assert summary.send_due(CONFIG, settings.get, utc("09:05"), history, tmp_path / "s.json", tmp_path, sent.append) == ["da40"]
