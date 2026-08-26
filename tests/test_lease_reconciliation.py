from app.core.lease_reconciliation import decide_claim_failure
from app.core.job_lease import JobLeaseStore


def test_missing_ledger_is_terminal_failure():
    decision = decide_claim_failure(None, owner="worker-a", now=100)
    assert (decision.action, decision.reason) == ("terminal_failure", "ledger_record_missing")


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
    assert diagnosis["action"] == "terminal_failure"
    assert diagnosis["reason"] == "ledger_record_missing"
