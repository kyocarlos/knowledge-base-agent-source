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
    monkeypatch.setattr(watch, "send_summaries", lambda config: summaries.append(1) or [])  # the daily summary has its own tests
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


def test_due_summaries_are_sent_from_the_watch_run_and_a_failure_never_stops_the_watching(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    summary_calls = []

    class Fake:
        @staticmethod
        def send_due(config, read_setting, now, history, state, root, send):
            summary_calls.append((sorted(config["zones"]), read_setting("test"), history.name, state.name))
            send("hello")
            return ["test"]

    sent = []

    class FakeNotify:
        @staticmethod
        def load_settings():
            return {"KM_NOTIFY_CHANNEL": "telegram"}

        @staticmethod
        def send(text, settings):
            sent.append(text)
            return ["telegram"]

    monkeypatch.setattr(watch, "_module", lambda name: Fake if name == "wifi8_quality_summary" else FakeNotify)
    monkeypatch.setattr(watch, "read_zone_json", lambda worker, name: {"enabled": True, "time": "09:00"} if name == "summary-notify.json" else None)
    monkeypatch.setattr(watch, "ROOT", tmp_path)
    assert watch.send_summaries({"zones": {"test": {"search_worker": "w"}}}) == ["test"]
    assert summary_calls == [(["test"], {"enabled": True, "time": "09:00"}, "history.jsonl", "summary-state.json")] and sent == ["hello"]

    def broken(name):
        raise RuntimeError("boom")

    monkeypatch.setattr(watch, "_module", broken)
    assert watch.send_summaries({"zones": {}}) == []  # logged, not raised
