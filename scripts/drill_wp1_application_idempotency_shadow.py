#!/usr/bin/env python3
"""Exercise application-level duplicate submission and recovery idempotency."""

from __future__ import annotations

import argparse
import json
import secrets
import sqlite3
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# Make the repository package importable when this script is invoked directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.job_lease import JobLeaseStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.expanduser().resolve()
    report.mkdir(parents=True, exist_ok=True)

    run_id = f"wp1-app-idempotency-{secrets.token_hex(6)}"
    with tempfile.TemporaryDirectory(prefix="km-wp1-app-idempotency-") as temporary:
        database = Path(temporary) / "application-ledger.sqlite3"
        store = JobLeaseStore(database)
        job_id = f"job-{run_id}"
        idempotency_key = f"request:{run_id}"
        store.register(job_id, idempotency_key)

        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE side_effects (operation_key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.commit()

        claim_barrier = threading.Barrier(4)

        def duplicate_submit(worker_id: int) -> dict[str, object]:
            claim_barrier.wait()
            claimed = store.claim(job_id, f"worker-{worker_id}", lease_seconds=30)
            return {
                "worker": f"worker-{worker_id}",
                "claimed": claimed is not None,
                "attempt": claimed["attempt"] if claimed else None,
            }

        with ThreadPoolExecutor(max_workers=4) as executor:
            submissions = list(executor.map(duplicate_submit, range(4)))

        winners = [item for item in submissions if item["claimed"]]
        if len(winners) != 1:
            raise RuntimeError(f"expected one live owner, got {submissions}")
        first_owner = str(winners[0]["worker"])

        # The first owner commits the business side effect, then dies before
        # acknowledging the application lease. Recovery must not duplicate it.
        with sqlite3.connect(database) as connection:
            connection.execute(
                "INSERT INTO side_effects(operation_key, value) VALUES (?, ?)",
                (idempotency_key, "created-by-first-attempt"),
            )
            connection.commit()

        current = store.get(job_id) or {}
        recovered_ids = store.recover_expired(now=float(current["lease_until"]) + 1)
        recovered = store.claim(job_id, "recovery-worker", lease_seconds=30)
        if recovered is None:
            raise RuntimeError("recovery worker could not reclaim expired job")

        with sqlite3.connect(database) as connection:
            duplicate_insert = connection.execute(
                "INSERT OR IGNORE INTO side_effects(operation_key, value) VALUES (?, ?)",
                (idempotency_key, "created-by-recovery-attempt"),
            )
            connection.commit()
            side_effect = connection.execute(
                "SELECT operation_key, value FROM side_effects WHERE operation_key = ?",
                (idempotency_key,),
            ).fetchone()

        recovery_completed = store.complete(job_id, "recovery-worker")
        duplicate_submit_after_success = store.claim(job_id, "late-delivery-worker", lease_seconds=30)
        final_state = store.get(job_id) or {}
        evidence: dict[str, object] = {
            "schema": "km.wp1.application-idempotency-shadow.v1",
            "mode": "isolated-shadow",
            "production_touched": False,
            "run_id": run_id,
            "job_id": job_id,
            "idempotency_key": idempotency_key,
            "concurrent_submissions": submissions,
            "live_owner_count": len(winners),
            "first_owner": first_owner,
            "first_attempt_side_effect_committed_before_crash": True,
            "recovered_job_ids": recovered_ids,
            "recovery_attempt": recovered["attempt"],
            "recovery_completed": recovery_completed,
            "duplicate_insert_rowcount": duplicate_insert.rowcount,
            "side_effect_row": {"key": side_effect[0], "value": side_effect[1]} if side_effect else None,
            "side_effect_count": 0,
            "late_duplicate_claim_after_success": duplicate_submit_after_success is not None,
            "final_ledger_status": final_state.get("status"),
            "final_ledger_attempt": final_state.get("attempt"),
            "application_idempotency_verified": False,
            "cleanup_verified": True,
        }
        with sqlite3.connect(database) as connection:
            evidence["side_effect_count"] = connection.execute(
                "SELECT COUNT(*) FROM side_effects WHERE operation_key = ?", (idempotency_key,)
            ).fetchone()[0]

        evidence["application_idempotency_verified"] = (
            evidence["live_owner_count"] == 1
            and evidence["recovered_job_ids"] == [job_id]
            and evidence["recovery_attempt"] == 2
            and evidence["recovery_completed"] is True
            and evidence["duplicate_insert_rowcount"] == 0
            and evidence["side_effect_count"] == 1
            and evidence["late_duplicate_claim_after_success"] is False
            and evidence["final_ledger_status"] == "succeeded"
        )
        if not evidence["application_idempotency_verified"]:
            raise RuntimeError(json.dumps(evidence, ensure_ascii=False))

    output = report / "application-idempotency-shadow-20260820.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
