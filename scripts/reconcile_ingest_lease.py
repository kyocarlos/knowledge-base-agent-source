#!/usr/bin/env python3
"""Safely inspect one ingest task's lease state before any retry or cleanup."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Allow direct execution from the repository root without requiring PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.job_lease import JobLeaseStore


def _redis_state(task_id: str) -> dict:
    import redis

    client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    raw = client.get(f"kb:ingest_task:{task_id}")
    if not raw:
        return {"present": False}
    try:
        state = json.loads(raw)
    except (TypeError, ValueError):
        return {"present": True, "parseable": False}
    return {
        "present": True,
        "parseable": True,
        "status": state.get("status"),
        "job_status": state.get("job_status"),
        "ingested": state.get("ingested"),
        "celery_task_present": bool(state.get("celery_task_id")),
    }


def build_evidence(task_id: str, ledger: Path) -> dict:
    store = JobLeaseStore(ledger)
    diagnosis = store.diagnose_claim_failure(task_id, owner="reconciliation-probe", now=time.time())
    row = diagnosis.pop("lease", None)
    return {
        "schema": "km.ingest-lease-reconciliation.v1",
        "task_id": task_id,
        "mode": "read-only",
        "ledger_path": str(ledger.resolve()),
        "ledger_record_present": row is not None,
        "ledger_status": row.get("status") if row else None,
        "ledger_attempt": row.get("attempt") if row else None,
        "ledger_recovery_count": row.get("recovery_count") if row else None,
        "lease_until_present": bool(row and row.get("lease_until")),
        "claim_action": diagnosis["action"],
        "claim_reason": diagnosis["reason"],
        "redis_state": _redis_state(task_id),
        "production_touched": False,
        "secrets_included": False,
        "retry_or_cleanup_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--ledger", type=Path, default=Path(os.getenv("KB_JOB_LEDGER_PATH", "data/job-ledger.sqlite3")))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true", help="reserved; reconciliation is not auto-applied")
    args = parser.parse_args()
    if args.apply:
        print("refusing --apply: task reconciliation requires an approved operator procedure", file=sys.stderr)
        return 2
    evidence = build_evidence(args.task_id, args.ledger)
    payload = json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        args.output.chmod(0o600)
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
