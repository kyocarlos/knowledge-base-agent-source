import sqlite3
import threading
import time

from app.core.lease_reconciliation import decide_claim_failure
from app.core.job_lease import JobLeaseStore


def test_missing_ledger_is_bounded_retry_during_initialization_window():
    decision = decide_claim_failure(None, owner="worker-a", now=100)
    assert (decision.action, decision.reason) == ("retry", "ledger_record_missing_transient")


def test_missing_ledger_terminalizes_only_after_retry_budget():
    decision = decide_claim_failure(None, owner="worker-a", now=100, retry_count=3, max_retries=3)
    assert (decision.action, decision.reason) == ("terminal_failure", "ledger_record_missing_retry_exhausted")


def test_active_foreign_lease_is_retryable():
    decision = decide_claim_failure(
        {"status": "running", "owner": "worker-a", "lease_until": 200},
        owner="worker-b",
        now=100,
    )
    assert (decision.action, decision.reason) == ("retry", "active_lease")


def test_completed_lease_is_idempotent_success():
    decision = decide_claim_failure(
        {"status": "succeeded", "owner": None, "lease_until": 0},
        owner="worker-b",
        now=100,
    )
    assert (decision.action, decision.reason) == ("idempotent_success", "already_completed")


def test_expired_or_inconsistent_running_lease_is_terminal_failure():
    decision = decide_claim_failure(
        {"status": "running", "owner": "worker-a", "lease_until": 50},
        owner="worker-b",
        now=100,
    )
    assert (decision.action, decision.reason) == ("terminal_failure", "claim_rejected_inconsistent_state")


def test_expired_lease_can_be_recovered_then_claimed_without_stealing():
    decision = decide_claim_failure(
        {"status": "running", "owner": "worker-a", "lease_until": 50},
        owner="worker-b",
        now=100,
    )
    assert decision.action == "terminal_failure"


def test_expired_running_lease_recovery_allows_next_worker_to_claim(tmp_path):
    store = JobLeaseStore(tmp_path / "ledger.sqlite3")
    store.register("expired-job", "expired-key")
    first = store.claim("expired-job", "worker-a", lease_seconds=60)
    assert first and first["owner"] == "worker-a"
    with store._connection() as connection:
        connection.execute("UPDATE job_leases SET lease_until=1 WHERE job_id=?", ("expired-job",))
    assert store.recover_expired(now=100) == ["expired-job"]
    second = store.claim("expired-job", "worker-b", lease_seconds=60)
    assert second and second["owner"] == "worker-b"


def test_foreign_active_lease_is_bounded_and_never_stealable():
    active = {"status": "running", "owner": "worker-a", "lease_until": 200}
    assert decide_claim_failure(active, owner="worker-b", now=100).action == "retry"
    exhausted = decide_claim_failure(active, owner="worker-b", now=100, retry_count=3, max_retries=3)
    assert exhausted.action == "terminal_failure"
    assert exhausted.reason == "active_lease_retry_exhausted"


def test_transaction_commit_race_is_observed_without_false_terminal_failure(tmp_path):
    store = JobLeaseStore(tmp_path / "ledger.sqlite3")
    connection = sqlite3.connect(store.database_path, isolation_level=None)
    now = time.time()
    connection.execute("BEGIN IMMEDIATE")
    connection.execute(
        "INSERT INTO job_leases (job_id, idempotency_key, status, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?)",
        ("race-job", "race-key", now, now),
    )
    result = {}

    def claim_after_commit():
        result["lease"] = store.claim("race-job", "worker-a", lease_seconds=60)

    thread = threading.Thread(target=claim_after_commit)
    thread.start()
    time.sleep(0.05)
    connection.execute("COMMIT")
    thread.join(timeout=2)
    connection.close()
    assert result["lease"]["owner"] == "worker-a"
    assert store.get("race-job")["status"] == "running"


def test_missing_ledger_retry_then_register_has_one_claimant(tmp_path):
    store = JobLeaseStore(tmp_path / "ledger.sqlite3")
    first = decide_claim_failure(None, owner="worker-a", now=100, retry_count=0, max_retries=3)
    assert first.action == "retry"
    store.register("queued-job", "request-key")
    winner = store.claim("queued-job", "worker-a", lease_seconds=60)
    loser = store.claim("queued-job", "worker-b", lease_seconds=60)
    assert winner and winner["owner"] == "worker-a"
    assert loser is None
    assert store.complete("queued-job", "worker-a") is True
    assert store.get("queued-job")["status"] == "succeeded"


def test_retry_budget_is_finite_and_terminal_reason_is_auditable():
    for retry_count in range(3):
        assert decide_claim_failure(None, owner="worker-a", now=100, retry_count=retry_count).action == "retry"
    final = decide_claim_failure(None, owner="worker-a", now=100, retry_count=3)
    assert final.action == "terminal_failure"
    assert final.reason == "ledger_record_missing_retry_exhausted"


def test_empty_ledger_and_queued_task_is_not_reported_as_success():
    decision = decide_claim_failure(None, owner="celery-task-id", now=100)
    assert decision.action != "idempotent_success"


def test_store_diagnosis_is_read_only_and_identifies_missing_row(tmp_path):
    store = JobLeaseStore(tmp_path / "ledger.sqlite3")
    before = store.get("missing")
    diagnosis = store.diagnose_claim_failure("missing", "worker-a", now=100)
    after = store.get("missing")
    assert before is None
    assert after is None
    assert diagnosis["action"] == "retry"
    assert diagnosis["reason"] == "ledger_record_missing_transient"
