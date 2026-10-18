#!/usr/bin/env python3
"""Controlled command client for the KM OpenClaw Anritsu delegation skill.

This client only talks to the localhost KM A2A bridge. It never accepts a
remote URL, an instrument command, or a real-execution flag from the caller.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


DEFAULT_TOKEN_FILE = Path("/home/da40_ai_gb10/knowledge-base/.km-a2a-control-token")
DEFAULT_BRIDGE_URL = "http://127.0.0.1:18181"
ALLOWED_CASES = ("sa_dl_tcp", "sa_ul_tcp")


def _request(url: str, token: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"bridge HTTP {exc.code}: {detail[:500]}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"bridge unavailable: {type(exc).__name__}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    submit = subparsers.add_parser("submit", help="submit one allowlisted dry-run job")
    submit.add_argument("--run-id", required=True)
    submit.add_argument("--requested-by", required=True)
    submit.add_argument("--duration", type=int, choices=range(1, 3601), default=60)
    submit.add_argument("--test-case", action="append", choices=ALLOWED_CASES, default=None)
    lookup = subparsers.add_parser("status", help="read one bridge task")
    lookup.add_argument("--run-id", required=True)
    args = parser.parse_args()

    token = DEFAULT_TOKEN_FILE.read_text(encoding="utf-8").strip()
    try:
        if args.command == "submit":
            if len(args.test_case) != len(set(args.test_case)):
                parser.error("test cases must be unique")
            payload = {
                "job_schema_version": "1.0",
                "dry_run": True,
                "job_type": "run_iperf_test",
                "environment": "anritsu",
                "profile_id": "ncq2200b2v-throughput-v1",
                "run_id": args.run_id,
                "requested_by": args.requested_by,
                "duration_seconds": args.duration,
                "test_cases": args.test_case or ["sa_dl_tcp"],
            }
            result = _request(f"{DEFAULT_BRIDGE_URL}/v1/tasks", token, method="POST", body=payload)
        else:
            result = _request(f"{DEFAULT_BRIDGE_URL}/v1/tasks/anritsu/{args.run_id}", token)
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        token = ""

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
