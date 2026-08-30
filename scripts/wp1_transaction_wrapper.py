#!/usr/bin/env python3
"""Fail-closed transaction wrapper that preserves acceptance failures."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from wp1_transaction_result import determine_result


def run_transaction(command: list[str], evidence_file: Path) -> int:
    """Run a transaction command and write one authoritative result record."""
    runner_exit: int | None = None
    exception_type: str | None = None
    try:
        completed = subprocess.run(command, check=False)
        runner_exit = completed.returncode
    except BaseException as exc:  # includes interruption during the transaction
        exception_type = type(exc).__name__
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
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("a transaction command is required")
    return run_transaction(args.command, args.evidence_file)


if __name__ == "__main__":
    raise SystemExit(main())
