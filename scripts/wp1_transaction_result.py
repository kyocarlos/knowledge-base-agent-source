#!/usr/bin/env python3
"""Authoritative result mapping for the WP1 maintenance transaction wrapper."""

from __future__ import annotations

import argparse
import json


def determine_result(
    runner_exit: int | None,
    *,
    evidence_complete: bool,
    exception_type: str | None = None,
    signal_number: int | None = None,
) -> str:
    """Return PASS only for a clean, complete runner termination."""
    if runner_exit != 0 or exception_type or signal_number is not None:
        return "FAIL_CLOSED"
    if not evidence_complete:
        return "FAIL_CLOSED"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner-exit", type=int, required=True)
    parser.add_argument("--evidence-complete", action="store_true")
    parser.add_argument("--exception-type")
    parser.add_argument("--signal-number", type=int)
    args = parser.parse_args()
    result = determine_result(
        args.runner_exit,
        evidence_complete=args.evidence_complete,
        exception_type=args.exception_type,
        signal_number=args.signal_number,
    )
    print(json.dumps({"runner_exit": args.runner_exit, "transaction_result": result}, sort_keys=True))
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
