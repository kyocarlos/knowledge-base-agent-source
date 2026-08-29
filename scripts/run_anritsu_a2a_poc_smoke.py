#!/usr/bin/env python3
"""Submit one fixed-schema Anritsu dry-run through the localhost KM bridge."""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CONTROL_TOKEN = Path("/home/da40_ai_gb10/knowledge-base/.km-a2a-control-token")
BRIDGE_URL = "http://127.0.0.1:18181/v1/tasks"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"poc-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}")
    parser.add_argument("--requested-by", default="km-agent-01")
    parser.add_argument("--duration", type=int, default=60, choices=range(1, 3601), metavar="1..3600")
    parser.add_argument("--test-case", action="append", choices=("sa_dl_tcp", "sa_ul_tcp"))
    parser.add_argument("--control-token-file", type=Path, default=DEFAULT_CONTROL_TOKEN)
    parser.add_argument("--timeout", type=int, default=90, choices=range(10, 301))
    args = parser.parse_args()
    if not SAFE_ID.fullmatch(args.run_id) or not SAFE_ID.fullmatch(args.requested_by):
        parser.error("run-id and requested-by must use safe identifier characters")
    test_cases = args.test_case or ["sa_dl_tcp"]
    if len(test_cases) != len(set(test_cases)) or len(test_cases) > 2:
        parser.error("test cases must be unique and limited to two")

    token = args.control_token_file.read_text(encoding="utf-8").strip()
    payload = {
        "job_schema_version": "1.0",
        "dry_run": True,
        "job_type": "run_iperf_test",
        "environment": "anritsu",
        "profile_id": "ncq2200b2v-throughput-v1",
        "run_id": args.run_id,
        "requested_by": args.requested_by,
        "duration_seconds": args.duration,
        "test_cases": test_cases,
    }
    request = urllib.request.Request(
        BRIDGE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            body = json.load(response)
    except urllib.error.HTTPError as exc:
        print(f"bridge rejected request: HTTP {exc.code}", file=sys.stderr)
        return 2
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"bridge or Anritsu transport unavailable: {type(exc).__name__}", file=sys.stderr)
        return 3
    finally:
        token = ""

    print(json.dumps(body, ensure_ascii=False, indent=2))
    if body.get("state") != "completed":
        return 4
    correlation = body.get("correlation", {})
    if correlation.get("openclaw_forward_status") != "accepted":
        return 6
    if correlation.get("openclaw_receiver") != "anritsu-openclaw":
        return 7
    if not correlation.get("openclaw_audit_id"):
        return 8
    if not all(correlation.get(key) for key in ("run_id", "context_id", "a2a_task_id")):
        return 9
    statuses = body.get("status", {})
    if statuses != {"test_status": "pending", "report_status": "pending", "ingest_status": "pending"}:
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
