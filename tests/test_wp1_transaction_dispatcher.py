import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/wp1_transaction_dispatcher.py"


def run_dispatch(tmp_path, exit_code, formal=True):
    evidence = tmp_path / "transaction.json"
    event_log = tmp_path / "orchestration.jsonl"
    env = {**os.environ, "WP1_FORMAL_ENTRYPOINT": "1" if formal else "0"}
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
            f"raise SystemExit({exit_code})",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    return result, evidence, event_log


def test_dispatcher_records_handoff_and_preserves_success(tmp_path):
    result, evidence, event_log = run_dispatch(tmp_path, 0)
    assert result.returncode == 0
    assert json.loads(evidence.read_text())["transaction_result"] == "PASS"
    events = [json.loads(line) for line in event_log.read_text().splitlines()]
    assert [event["event"] for event in events] == [
        "dispatcher_launch_pre",
        "runner_launch_pre",
        "runner_complete",
        "dispatcher_complete",
    ]
    assert events[-1]["wrapper_exit"] == 0


def test_dispatcher_preserves_fail_closed_result(tmp_path):
    result, evidence, event_log = run_dispatch(tmp_path, 7)
    assert result.returncode == 1
    assert json.loads(evidence.read_text()) == {"runner_exit": 7, "transaction_result": "FAIL_CLOSED"}
    events = [json.loads(line) for line in event_log.read_text().splitlines()]
    assert events[-1]["event"] == "dispatcher_complete"
    assert events[-1]["wrapper_exit"] == 1


def test_dispatcher_rejects_non_formal_caller(tmp_path):
    result, evidence, event_log = run_dispatch(tmp_path, 0, formal=False)
    assert result.returncode == 1
    assert not evidence.exists()
    events = [json.loads(line) for line in event_log.read_text().splitlines()]
    assert events[-1]["event"] == "dispatcher_rejected_non_formal_caller"
