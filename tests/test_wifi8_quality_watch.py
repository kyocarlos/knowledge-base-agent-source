import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


watch = load("wifi8_quality_watch")
A = {"package_id": "wifi8-a", "switched_at": "2026-10-18T12:00:00+00:00"}
B = {"package_id": "wifi8-b", "switched_at": "2026-10-19T09:00:00+00:00"}


def test_the_first_poll_only_records_what_is_served():
    state, run = watch.decide(None, A)
    assert not run and state["checked"] == A and state["pending"] is None
    assert watch.decide({"checked": A}, None) == ({"checked": A}, False)  # unreadable: nothing changes


def test_a_change_must_be_seen_in_consecutive_polls_before_a_check_runs():
    state, run = watch.decide({"checked": A, "pending": None, "attempts": 0}, B, settle_polls=2)
    assert not run and state["pending"]["polls"] == 1
    state, run = watch.decide(state, B, settle_polls=2)
    assert run and state["pending"]["polls"] == 2


def test_a_package_that_flips_back_or_changes_again_starts_over():
    state, _ = watch.decide({"checked": A}, B, 2)
    state, run = watch.decide(state, A, 2)  # back to the checked package: nothing to check
    assert not run and state["pending"] is None
    state, _ = watch.decide({"checked": A}, B, 2)
    state, run = watch.decide(state, {**B, "switched_at": "2026-10-19T09:05:00+00:00"}, 2)  # published again meanwhile
    assert not run and state["pending"]["polls"] == 1


def test_publishing_the_same_package_again_counts_as_a_change():
    again = {**A, "switched_at": "2026-10-19T10:00:00+00:00"}
    state, _ = watch.decide({"checked": A}, again, 2)
    state, run = watch.decide(state, again, 2)
    assert run
    quality = load("wifi8_quality_check")
    assert "重新發布" in quality.describe_change("test", A, again)
    assert quality.describe_change("da40", A, B) == "DA40：wifi8-a → wifi8-b"


class Sandbox(tuple):
    """(served, sent, runs) plus the page switches (.enabled) and the statuses written to each zone (.written)."""


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "ROOT", tmp_path)
    monkeypatch.setattr(watch, "STATE", tmp_path / "package-state.json")
    monkeypatch.setattr(watch, "LOCK", tmp_path / "quality.lock")
    served = {"kb-celery-search": A, "km-da40-celery_search_worker-1": A}
    monkeypatch.setattr(watch, "read_current", lambda worker: served[worker])
    sent, runs = [], []
    monkeypatch.setattr(watch, "notify_text", sent.append)
    summaries = []
    monkeypatch.setattr(watch, "run_schedules", lambda config: summaries.append(1) or [])  # the scheduled checks have their own tests
    enabled = {"kb-celery-search": True, "km-da40-celery_search_worker-1": True}
    written = {}
    monkeypatch.setattr(watch, "read_enabled", lambda worker: enabled[worker])
    monkeypatch.setattr(watch, "write_status", lambda worker, status: written.__setitem__(worker, status) or True)
    box = Sandbox((served, sent, runs))
    box.enabled, box.written = enabled, written
    return box


def fake_check(monkeypatch, runs, code):
    def run(args, **kwargs):
        runs.append(args)
        return subprocess.CompletedProcess(args, code, stdout="", stderr="boom")
    monkeypatch.setattr(watch.subprocess, "run", run)


def test_a_new_package_starts_one_check_for_the_changed_zone_only(sandbox, monkeypatch):  # noqa: D103
    served, sent, runs = sandbox
    fake_check(monkeypatch, runs, 3)  # WARN still means the check ran
    monkeypatch.setattr(watch.sys, "argv", ["watch"])
    assert watch.main() == 0 and not runs  # first poll: baseline
    served["kb-celery-search"] = B
    assert watch.main() == 0 and not runs  # first sight of the change
    assert watch.main() == 0
    assert len(runs) == 1
    args = runs[0]
    assert args[args.index("--trigger") + 1] == "package_change" and args[args.index("--zones") + 1] == "test"
    changes = json.loads(args[args.index("--changes") + 1])
    assert changes[0]["zone"] == "test" and changes[0]["before"] == A and changes[0]["after"]["package_id"] == "wifi8-b"
    assert watch.main() == 0 and len(runs) == 1  # checked: no repeat
    assert json.loads(watch.STATE.read_text())["test"]["checked"] == B and not sent


def test_a_check_that_cannot_run_is_retried_then_reported(sandbox, monkeypatch):
    served, sent, runs = sandbox
    fake_check(monkeypatch, runs, 2)
    monkeypatch.setattr(watch.sys, "argv", ["watch"])
    watch.main()
    served["km-da40-celery_search_worker-1"] = B
    for _ in range(2):
        watch.main()
    assert len(runs) == 1 and not sent
    state = json.loads(watch.STATE.read_text())["da40"]
    assert state["attempts"] == 1 and state["checked"] == A  # still owed
    for _ in range(4):
        watch.main()
    assert len(runs) == 3 and len(sent) == 1 and "連續 3 次無法執行" in sent[0] and "DA40" in sent[0]
    assert json.loads(watch.STATE.read_text())["da40"]["checked"] == B  # given up: no endless loop


def test_a_running_check_delays_the_new_one(sandbox, monkeypatch):
    import fcntl
    served, sent, runs = sandbox
    fake_check(monkeypatch, runs, 0)
    monkeypatch.setattr(watch.sys, "argv", ["watch"])
    watch.main()
    served["kb-celery-search"] = B
    watch.main()
    with watch.LOCK.open("w") as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        assert watch.main() == 0 and not runs  # the other check holds the lock
    assert watch.main() == 0 and len(runs) == 1  # runs as soon as the lock is free


def test_a_zone_switched_off_on_its_page_is_not_checked_until_it_is_switched_on_again(sandbox, monkeypatch):
    served, sent, runs = sandbox
    fake_check(monkeypatch, runs, 0)
    monkeypatch.setattr(watch.sys, "argv", ["watch"])
    watch.main()
    sandbox.enabled["kb-celery-search"] = False
    served["kb-celery-search"] = B
    for _ in range(3):
        watch.main()
    assert not runs  # switched off: the change is neither polled nor checked
    assert sandbox.written["kb-celery-search"]["enabled"] is False and sandbox.written["kb-celery-search"]["watching"]["package_id"] == "wifi8-b"
    assert json.loads(watch.STATE.read_text())["test"]["checked"] == A  # still owed
    sandbox.enabled["kb-celery-search"] = True
    watch.main()
    watch.main()
    assert len(runs) == 1  # the change made while it was off is checked once it is on again


def test_every_run_tells_each_zone_page_that_the_watcher_is_alive_and_what_it_last_did(sandbox, monkeypatch):
    served, sent, runs = sandbox
    fake_check(monkeypatch, runs, 0)
    monkeypatch.setattr(watch.sys, "argv", ["watch"])
    (watch.ROOT / "latest.json").write_text(json.dumps({"created_utc": "2026-10-19T09:00:00+00:00", "zones": {"test": {"_status": "PASS"}}}))
    watch.main()
    status = sandbox.written["kb-celery-search"]
    assert status["enabled"] is True and status["interval_minutes"] == 5 and status["last_poll_at"] and status["last_check"] is None
    served["kb-celery-search"] = B
    watch.main()
    watch.main()
    last = sandbox.written["kb-celery-search"]["last_check"]
    assert last == {"at": "2026-10-19T09:00:00+00:00", "status": "PASS", "package_id": "wifi8-b", "trigger": "package_change"}
    assert sandbox.written["km-da40-celery_search_worker-1"]["last_check"] is None  # the other zone did not change


class _Done:
    def __init__(self, code, out=""):
        self.returncode, self.stdout, self.stderr = code, out, ""


@pytest.fixture
def scheduled(tmp_path, monkeypatch):
    """Watch with a real schedule module, one due zone ("test", default 03:30) and fakes for the check and the notifier."""
    from datetime import datetime, timezone
    monkeypatch.setattr(watch, "ROOT", tmp_path)
    monkeypatch.setattr(watch, "LOCK", tmp_path / "quality.lock")
    calls, notices = [], []
    monkeypatch.setattr(watch, "read_zone_json", lambda worker, name: None)
    monkeypatch.setattr(watch, "notify_text", notices.append)
    monkeypatch.setattr(watch.subprocess, "run", lambda args, **kw: calls.append(args) or _Done(0))
    monkeypatch.setattr(watch, "datetime", type("D", (datetime,), {"now": classmethod(lambda cls, tz=None: datetime(2026, 10, 20, 3, 40, tzinfo=timezone(__import__("datetime").timedelta(hours=8))).astimezone(tz or timezone.utc))}))
    return {"zones": {"test": {"search_worker": "w"}}}, calls, notices, tmp_path


def test_a_due_zone_is_checked_once_with_the_schedule_trigger_and_the_daily_levels(scheduled):
    config, calls, notices, root = scheduled
    assert watch.run_schedules(config) == ["test"]
    assert len(calls) == 1 and calls[0][-6:] == ["--trigger", "schedule", "--zones", "test", "--levels", "retrieval,trust"][-6:] and not notices
    assert watch.run_schedules(config) == [] and len(calls) == 1  # done for today
    assert json.loads((root / "schedule-state.json").read_text())["test"]["last_run_date"] == "2026-10-20"


def test_a_check_that_cannot_run_is_reported_each_time_then_given_up_for_the_day(scheduled, monkeypatch):
    config, calls, notices, root = scheduled
    monkeypatch.setattr(watch.subprocess, "run", lambda args, **kw: calls.append(args) or _Done(2, "boom"))
    for _ in range(5):
        watch.run_schedules(config)
    assert len(calls) == 3 and len(notices) == 3  # max_attempts, every failure is told to the user
    assert "執行失敗" in notices[0] and "第 1/3 次" in notices[0] and "第 3/3 次" in notices[2] and "boom" in notices[0]


def test_a_timeout_counts_as_a_failure(scheduled, monkeypatch):
    config, calls, notices, root = scheduled

    def hang(args, **kw):
        raise watch.subprocess.TimeoutExpired(args, 7200)

    monkeypatch.setattr(watch.subprocess, "run", hang)
    assert watch.run_schedules(config) == [] and "逾時" in notices[0]


def test_a_check_that_is_running_delays_the_scheduled_one(scheduled):
    import fcntl
    config, calls, notices, root = scheduled
    with (root / "quality.lock").open("w") as holder:
        fcntl.flock(holder, fcntl.LOCK_EX)
        assert watch.run_schedules(config) == [] and not calls
    assert watch.run_schedules(config) == ["test"]  # the next poll gets it


def test_a_bug_in_the_scheduler_is_told_once_a_day_and_never_stops_the_watching(scheduled, monkeypatch):
    config, calls, notices, root = scheduled
    real = watch._module
    monkeypatch.setattr(watch, "_module", lambda name: (_ for _ in ()).throw(RuntimeError("boom")) if name == "wifi8_quality_notify" else real(name))
    assert watch.run_schedules(config) == [] and watch.run_schedules(config) == []
    assert len(notices) == 1 and "判斷程式出錯" in notices[0]
