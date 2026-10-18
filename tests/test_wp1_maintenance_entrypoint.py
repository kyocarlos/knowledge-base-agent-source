import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/wp1_maintenance_entrypoint.py"


def test_entrypoint_persists_supervision_and_dispatch_events(tmp_path):
    evidence = tmp_path / "transaction.json"
    event_log = tmp_path / "orchestration.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--evidence-file",
            str(evidence),
            "--orchestration-log",
            str(event_log),
            "--heartbeat-interval",
            "0.02",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(0.08)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    events = [json.loads(line) for line in event_log.read_text().splitlines()]
    names = [event["event"] for event in events]
    assert names[0:3] == ["entrypoint_start", "entrypoint_dispatch_pre", "dispatcher_launch_pre"]
    assert "runner_launch_pre" in names
    assert "runner_complete" in names
    assert names[-1] == "entrypoint_complete"
    assert events[-1]["entrypoint_exit"] == 0
    assert any(event["event"] == "entrypoint_heartbeat" for event in events)


def test_entrypoint_preserves_fail_closed_exit(tmp_path):
    evidence = tmp_path / "transaction.json"
    event_log = tmp_path / "orchestration.jsonl"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--evidence-file",
            str(evidence),
            "--orchestration-log",
            str(event_log),
            "--",
            sys.executable,
            "-c",
            "raise SystemExit(9)",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert json.loads(evidence.read_text())["transaction_result"] == "FAIL_CLOSED"
    events = [json.loads(line) for line in event_log.read_text().splitlines()]
    assert events[-1]["event"] == "entrypoint_complete"
    assert events[-1]["entrypoint_exit"] == 1
