#!/usr/bin/env python3
"""Verify the isolated write-E2E acceptance evidence without enabling production writes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


RUN_ID = re.compile(r"^TR-E2E-WP0-[A-Za-z0-9._:-]+$")


def verify(path: Path) -> dict:
    evidence = json.loads(path.read_text(encoding="utf-8"))
    write = evidence
    required = {
        "result": "passed",
        "production_services_touched": False,
        "checks": dict,
    }
    for key, expected in required.items():
        if key not in write:
            raise ValueError(f"缺少必要欄位: {key}")
        if expected is dict and not isinstance(write[key], dict):
            raise ValueError(f"欄位格式錯誤: {key}")
        elif expected is not dict and write[key] != expected:
            raise ValueError(f"欄位不符合 shadow-only Gate: {key}")

    test_run_id = str(write.get("test_run_id", ""))
    if not RUN_ID.fullmatch(test_run_id):
        raise ValueError("test_run_id 不符合隔離 E2E prefix")
    checks = write["checks"]
    expected_checks = {
        "report_upload": "HTTP 202",
        "review_approve_and_queue": "HTTP 200",
        "worker_terminal_state": "completed",
        "cleanup_dry_run": "HTTP 200",
        "cleanup_apply": "HTTP 200",
        "submission_after_cleanup": "HTTP 404",
    }
    for key, expected in expected_checks.items():
        if checks.get(key) != expected:
            raise ValueError(f"Gate check 未通過: {key}")

    neo4j_before = checks.get("neo4j_scoped_counts_before_cleanup") or {}
    neo4j_deleted = checks.get("neo4j_deleted_counts") or {}
    for label in ("TestRun", "TestCase", "Measurement"):
        if int(neo4j_before.get(label, 0)) <= 0 or neo4j_deleted.get(label) != neo4j_before[label]:
            raise ValueError(f"Neo4j scoped cleanup count 不一致: {label}")
    qdrant_before = int(checks.get("qdrant_scoped_points_before_cleanup", 0))
    qdrant_deleted = int(checks.get("qdrant_deleted_points", -1))
    if qdrant_before <= 0 or qdrant_deleted != qdrant_before:
        raise ValueError("Qdrant scoped cleanup count 不一致")

    return {
        "valid": True,
        "decision": "SHADOW_WRITE_E2E_PASS",
        "production_ready": False,
        "test_run_id": test_run_id,
        "neo4j_scoped_counts": neo4j_before,
        "qdrant_scoped_points": qdrant_before,
        "cleanup_reconciled": True,
        "production_write_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.evidence), ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
