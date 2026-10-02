from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from km_a2a_bridge import (
    RealRunApproval,
    RealRunCorrelation,
    RealRunJob,
    RealRunResponse,
    RealRunState,
    validate_real_run_approval,
)


NOW = datetime(2026, 8, 13, 4, 30, tzinfo=timezone.utc)


def valid_approval(**overrides):
    values = {
        "approval_id": "approval-1",
        "run_id": "real-run-1",
        "operator_id": "operator@example.test",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
    }
    values.update(overrides)
    return RealRunApproval(**values)


def valid_job(**overrides):
    values = {
        "job_type": "run_iperf_test",
        "environment": "anritsu",
        "profile_id": "ncq2200b2v-throughput-v1",
        "run_id": "real-run-1",
        "requested_by": "operator@example.test",
        "duration_seconds": 60,
        "test_cases": ["sa_dl_tcp"],
        "approval": valid_approval(),
    }
    values.update(overrides)
    return RealRunJob(**values)


def test_real_contract_is_explicitly_not_dry_run_and_requires_one_case():
    job = valid_job()
    assert job.dry_run is False
    assert job.test_cases == ["sa_dl_tcp"]

    with pytest.raises(ValidationError):
        valid_job(test_cases=["sa_dl_tcp", "sa_ul_tcp"])


def test_real_contract_rejects_dry_run_true_and_extra_fields():
    with pytest.raises(ValidationError):
        valid_job(dry_run=True)
    with pytest.raises(ValidationError):
        valid_job(shell_command="iperf --version")


def test_approval_is_bound_to_run_and_operator():
    with pytest.raises(ValidationError, match="different run_id"):
        valid_job(approval=valid_approval(run_id="other-run"))
    with pytest.raises(ValidationError, match="does not match"):
        valid_job(approval=valid_approval(operator_id="other@example.test"))


def test_approval_requires_timezone_and_max_15_minute_lifetime():
    with pytest.raises(ValidationError, match="timezone"):
        valid_approval(issued_at=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError, match="15 minute"):
        valid_approval(expires_at=NOW + timedelta(minutes=16))


def test_approval_validation_checks_current_window():
    job = valid_job()
    validate_real_run_approval(job, now=NOW + timedelta(minutes=1))
    with pytest.raises(ValueError, match="not active"):
        validate_real_run_approval(job, now=NOW - timedelta(seconds=1))
    with pytest.raises(ValueError, match="expired"):
        validate_real_run_approval(job, now=NOW + timedelta(minutes=5))


def test_completed_response_requires_artifact_and_ingest():
    base = {
        "state": RealRunState.COMPLETED,
        "test_status": "completed",
        "report_status": "completed",
        "ingest_status": "completed",
    }
    correlation = {
        "run_id": "real-run-1",
        "context_id": "ctx-1",
        "a2a_task_id": "task-1",
        "approval_id": "approval-1",
        "execution_owner": "anritsu-openclaw",
        "audit_id": "audit-1",
    }
    with pytest.raises(ValidationError, match="artifact hash"):
        RealRunResponse(correlation=correlation, **base)

    response = RealRunResponse(
        correlation={
            **correlation,
            "artifact_sha256": "a" * 64,
            "ingest_task_id": "ingest-1",
        },
        **base,
    )
    assert response.state is RealRunState.COMPLETED


def test_correlation_rejects_invalid_artifact_hash():
    with pytest.raises(ValidationError):
        RealRunCorrelation(
            run_id="run-1",
            context_id="ctx-1",
            a2a_task_id="task-1",
            approval_id="approval-1",
            execution_owner="anritsu-openclaw",
            audit_id="audit-1",
            artifact_sha256="not-a-sha256",
        )
