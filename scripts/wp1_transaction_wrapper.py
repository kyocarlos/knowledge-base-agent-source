#!/usr/bin/env python3
"""Fail-closed transaction wrapper that preserves acceptance failures."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from wp1_transaction_result import determine_result


def _safe_command(command: list[str]) -> list[str]:
    """Keep orchestration logs free of credential-like argument values."""
    sensitive = ("token", "secret", "password", "passwd", "api-key", "apikey", "cookie", "authorization")
    safe: list[str] = []
    redact_next = False
    for value in command:
        if redact_next:
            safe.append("[REDACTED]")
            redact_next = False
            continue
        lowered = value.lower()
        if any(marker in lowered for marker in sensitive) and ("=" not in value or value.split("=", 1)[0].lower() in sensitive):
            if "=" in value:
                safe.append(value.split("=", 1)[0] + "=[REDACTED]")
            else:
                safe.append(value)
                redact_next = True
            continue
        safe.append(value)
    return safe


def _append_event(log_file: Path | None, event: str, **fields: object) -> None:
    if log_file is None:
        return
    record = {
        "event": event,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "secrets_included": False,
        **fields,
    }
    with log_file.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def run_transaction(command: list[str], evidence_file: Path, orchestration_log: Path | None = None) -> int:
    """Run a transaction command and write one authoritative result record."""
    runner_exit: int | None = None
    exception_type: str | None = None
    if os.environ.get("WP1_DISPATCHER_CONTEXT") != "1":
        _append_event(orchestration_log, "wrapper_rejected_non_dispatcher", reason="dispatcher context missing")
        evidence_file.write_text(
            json.dumps({"runner_exit": None, "transaction_result": "FAIL_CLOSED"}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 1
    _append_event(orchestration_log, "runner_launch_pre", command=_safe_command(command))
    try:
        completed = subprocess.run(command, check=False)
        runner_exit = completed.returncode
        _append_event(orchestration_log, "runner_complete", runner_exit=runner_exit)
    except BaseException as exc:  # includes interruption during the transaction
        exception_type = type(exc).__name__
        _append_event(orchestration_log, "runner_exception", exception_type=exception_type)
    result = determine_result(
        runner_exit,
        evidence_complete=runner_exit == 0 and exception_type is None,
        exception_type=exception_type,
    )
    evidence_file.write_text(
        json.dumps(
            {"runner_exit": runner_exit, "transaction_result": result},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0 if result == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--orchestration-log", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("a transaction command is required")
    return run_transaction(args.command, args.evidence_file, args.orchestration_log)


if __name__ == "__main__":
    raise SystemExit(main())
