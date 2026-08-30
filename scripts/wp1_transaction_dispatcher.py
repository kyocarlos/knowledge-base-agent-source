#!/usr/bin/env python3
"""Versioned dispatcher for an auditable WP1 transaction handoff."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from wp1_transaction_wrapper import _safe_command


def _event(log_file: Path, event: str, **fields: object) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "event": event,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "secrets_included": False,
        **fields,
    }
    with log_file.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def dispatch(wrapper: Path, command: list[str], evidence_file: Path, event_log: Path) -> int:
    """Invoke the wrapper and make the handoff observable and fail-closed."""
    if os.environ.get("WP1_FORMAL_ENTRYPOINT") != "1":
        _event(event_log, "dispatcher_rejected_non_formal_caller", reason="formal entrypoint marker missing")
        return 1
    wrapper_command = [
        sys.executable,
        str(wrapper),
        "--evidence-file",
        str(evidence_file),
        "--orchestration-log",
        str(event_log),
        "--",
        *command,
    ]
    _event(event_log, "dispatcher_launch_pre", command=_safe_command(command))
    try:
        environment = {**os.environ, "WP1_DISPATCHER_CONTEXT": "1"}
        completed = subprocess.run(wrapper_command, check=False, env=environment)
    except BaseException as exc:  # noqa: BLE001
        _event(event_log, "dispatcher_exception", exception_type=type(exc).__name__)
        return 1
    _event(event_log, "dispatcher_complete", wrapper_exit=completed.returncode)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wrapper", type=Path, default=Path(__file__).with_name("wp1_transaction_wrapper.py"))
    parser.add_argument("--evidence-file", type=Path, required=True)
    parser.add_argument("--orchestration-log", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command[:1] == ["--"]:
        args.command = args.command[1:]
    if not args.command:
        parser.error("a transaction command is required")
    return dispatch(args.wrapper, args.command, args.evidence_file, args.orchestration_log)


if __name__ == "__main__":
    raise SystemExit(main())
