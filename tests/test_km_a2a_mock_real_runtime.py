from datetime import datetime, timedelta, timezone

import pytest

from km_a2a_bridge import RealRunApproval, RealRunJob
from km_a2a_bridge.mock_real_runtime import MockRealRunController, MockRealRunError, MockRealRunPolicy


NOW = datetime(2026, 8, 13, 5, 0, tzinfo=timezone.utc)


def job(run_id="real-run-1", approval_id="approval-1", duration_seconds=60):
    return RealRunJob(
        job_type="run_iperf_test",
        environment="anritsu",
        profile_id="ncq2200b2v-throughput-v1",
        run_id=run_id,
        requested_by="operator@example.test",
        duration_seconds=duration_seconds,
        test_cases=["sa_dl_tcp"],
        approval=RealRunApproval(
            approval_id=approval_id,
            run_id=run_id,
            operator_id="operator@example.test",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        ),
    )


def controller(lock_lease_seconds=120):
    return MockRealRunController(
        MockRealRunPolicy(
            allowed_profiles=frozenset({"ncq2200b2v-throughput-v1"}),
            allowed_test_cases=frozenset({"sa_dl_tcp"}),
            lock_lease_seconds=lock_lease_seconds,
        )
    )


def test_submit_consumes_single_use_approval_and_acquires_lock():
    runtime = controller()
    response = runtime.submit(job(), NOW)
    assert response.state.value == "queued"
    assert response.correlation.instrument_lock_id
    with pytest.raises(MockRealRunError, match="already been used"):
        runtime.submit(job(run_id="real-run-2"), NOW)


def test_lock_is_single_flight_until_cancel():
    runtime = controller()
    runtime.submit(job(), NOW)
    with pytest.raises(MockRealRunError, match="lock is busy"):
        runtime.submit(job(run_id="real-run-2", approval_id="approval-2"), NOW)
    canceled = runtime.cancel("real-run-1", NOW)
    assert canceled.state.value == "canceled"
    assert runtime.submit(job(run_id="real-run-2", approval_id="approval-2"), NOW).state.value == "queued"


def test_timeout_releases_lock_and_marks_safe_state_required():
    runtime = controller()
    runtime.submit(job(duration_seconds=1), NOW)
    expired = runtime.timeout_due_runs(NOW + timedelta(seconds=1))
    assert len(expired) == 1
    assert expired[0].state.value == "canceled"
    with pytest.raises(MockRealRunError, match="already been submitted"):
        runtime.submit(job(), NOW + timedelta(seconds=1))
    assert runtime.submit(job(run_id="real-run-3", approval_id="approval-3"), NOW + timedelta(seconds=1)).state.value == "queued"


def test_complete_hashes_artifact_and_releases_lock():
    runtime = controller()
    runtime.submit(job(), NOW)
    response = runtime.complete("real-run-1", b"mock-xlsx-bytes", "ingest-1")
    assert response.state.value == "completed"
    assert response.correlation.artifact_sha256
    assert response.correlation.ingest_task_id == "ingest-1"
    assert runtime.submit(job(run_id="real-run-2", approval_id="approval-2"), NOW).state.value == "queued"


def test_empty_artifact_does_not_complete_or_release_lock():
    runtime = controller()
    runtime.submit(job(), NOW)
    with pytest.raises(MockRealRunError, match="must not be empty"):
        runtime.complete("real-run-1", b"", "ingest-1")
    with pytest.raises(MockRealRunError, match="lock is busy"):
        runtime.submit(job(run_id="real-run-2", approval_id="approval-2"), NOW)


def test_expired_lock_is_recovered_before_next_submit():
    runtime = controller(lock_lease_seconds=1)
    runtime.submit(job(), NOW)
    next_response = runtime.submit(job(run_id="real-run-2", approval_id="approval-2"), NOW + timedelta(seconds=1))
    assert next_response.state.value == "queued"
