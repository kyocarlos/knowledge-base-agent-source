from app.core.job_lease import JobLeaseStore


def test_expired_lease_is_recovered_and_reclaimed(tmp_path):
    store = JobLeaseStore(tmp_path / "ledger.sqlite3")
    store.register("job-1", "idempotency-1")
    claimed = store.claim("job-1", "worker-a", lease_seconds=1)
    assert claimed["attempt"] == 1

    recovered = store.recover_expired(now=claimed["lease_until"] + 1)
    assert recovered == ["job-1"]
    reclaimed = store.claim("job-1", "worker-b", lease_seconds=30)
    assert reclaimed["attempt"] == 2
    assert reclaimed["recovery_count"] == 1


def test_only_owner_can_complete_and_completion_is_single_use(tmp_path):
    store = JobLeaseStore(tmp_path / "ledger.sqlite3")
    store.register("job-1")
    store.claim("job-1", "worker-a", lease_seconds=30)
    assert store.complete("job-1", "worker-b") is False
    assert store.complete("job-1", "worker-a") is True
    assert store.complete("job-1", "worker-a") is False
    assert store.get("job-1")["status"] == "succeeded"


def test_non_retryable_failure_is_terminal(tmp_path):
    store = JobLeaseStore(tmp_path / "ledger.sqlite3")
    store.register("job-1")
    store.claim("job-1", "worker-a", lease_seconds=30)
    assert store.fail("job-1", "worker-a") is True
    assert store.recover_expired(now=10**12) == []
    assert store.get("job-1")["status"] == "failed"


def test_claim_race_allows_only_one_live_owner(tmp_path):
    store = JobLeaseStore(tmp_path / "ledger.sqlite3")
    store.register("job-1")
    assert store.claim("job-1", "worker-a", lease_seconds=30)
    assert store.claim("job-1", "worker-b", lease_seconds=30) is None
