#!/usr/bin/env python3
"""Run a bounded, dry-run-only Anritsu OpenClaw receiver monitor."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOG = Path("/home/da40_ai_gb10/.local/state/km-a2a/anritsu-openclaw-2day.jsonl")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def run_sample(log_path: Path, sequence: int, timeout: int) -> bool:
    run_id = f"openclaw-2day-{utc_now():%Y%m%dT%H%M%SZ}-{sequence:04d}"
    command = [
        sys.executable,
        str(ROOT / "scripts/run_anritsu_a2a_poc_smoke.py"),
        "--run-id", run_id,
        "--requested-by", "km-openclaw-2day-monitor",
        "--duration", "1",
        "--test-case", "sa_dl_tcp",
        "--timeout", str(timeout),
    ]
    started = utc_now()
    try:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout + 15)
        output = completed.stdout.strip()
        payload = json.loads(output) if output else {}
        result = {
            "observed_at": started.isoformat(),
            "sequence": sequence,
            "run_id": run_id,
            "return_code": completed.returncode,
            "task": payload,
        }
        ok = (
            completed.returncode == 0
            and payload.get("state") == "completed"
            and payload.get("correlation", {}).get("openclaw_forward_status") == "accepted"
            and payload.get("correlation", {}).get("openclaw_receiver") == "anritsu-openclaw"
            and bool(payload.get("correlation", {}).get("openclaw_audit_id"))
            and all(value == 0 for value in payload.get("correlation", {}).get("dry_run_side_effect_counts", {}).values())
        )
        result["gate"] = "PASS" if ok else "FAIL"
        if completed.stderr.strip():
            result["stderr"] = completed.stderr[-1000:]
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        result = {"observed_at": started.isoformat(), "sequence": sequence, "run_id": run_id, "gate": "FAIL", "error": type(exc).__name__}
        ok = False
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=48, choices=(48,))
    parser.add_argument("--interval-seconds", type=int, default=1800, choices=range(300, 86401))
    parser.add_argument("--sample-timeout", type=int, default=90, choices=range(30, 301))
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    args = parser.parse_args()
    deadline = utc_now() + timedelta(hours=args.hours)
    sequence = 1
    failures = 0
    while utc_now() < deadline:
        if not run_sample(args.log, sequence, args.sample_timeout):
            failures += 1
        sequence += 1
        remaining = (deadline - utc_now()).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(args.interval_seconds, remaining))
    print(json.dumps({"log": str(args.log), "samples": sequence - 1, "failures": failures, "finished_at": utc_now().isoformat()}, ensure_ascii=False))
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
