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


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "ROOT", tmp_path)
    monkeypatch.setattr(watch, "STATE", tmp_path / "package-state.json")
    monkeypatch.setattr(watch, "LOCK", tmp_path / "quality.lock")
    served = {"kb-celery-search": A, "km-da40-celery_search_worker-1": A}
    monkeypatch.setattr(watch, "read_current", lambda worker: served[worker])
    sent, runs = [], []
    monkeypatch.setattr(watch, "notify_text", sent.append)
    return served, sent, runs


def fake_check(monkeypatch, runs, code):
    def run(args, **kwargs):
        runs.append(args)
        return subprocess.CompletedProcess(args, code, stdout="", stderr="boom")
    monkeypatch.setattr(watch.subprocess, "run", run)


def test_a_new_package_starts_one_check_for_the_changed_zone_only(sandbox, monkeypatch):
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
