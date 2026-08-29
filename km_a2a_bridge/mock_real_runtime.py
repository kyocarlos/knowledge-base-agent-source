"""Failure-injection runtime for the independent real-run contract.

This module is deliberately in-memory and mock-only. It does not make network
calls, start processes, acquire hardware, or write KM ingest records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

from .real_contracts import (
    RealRunJob,
    RealRunResponse,
    RealRunState,
    RealRunCorrelation,
    validate_real_run_approval,
)


class MockRealRunError(RuntimeError):
    """Expected policy or lifecycle rejection in the mock runtime."""


@dataclass(frozen=True)
class MockRealRunPolicy:
    allowed_profiles: frozenset[str]
    allowed_test_cases: frozenset[str]
    lock_lease_seconds: int = 120


@dataclass
class _MockRecord:
    job: RealRunJob
    state: RealRunState
    submitted_at: datetime
    deadline: datetime
    lock_id: str
    context_id: str
    a2a_task_id: str
    audit_id: str
    artifact_sha256: str | None = None
    ingest_task_id: str | None = None
    reason: str | None = None


class MockRealRunController:
    """Deterministic controller used to validate R1 safety behavior."""

    def __init__(self, policy: MockRealRunPolicy):
        if policy.lock_lease_seconds < 1:
            raise ValueError("lock lease must be positive")
        self.policy = policy
        self._records: dict[str, _MockRecord] = {}
        self._used_approvals: set[str] = set()
        self._active_lock: _MockRecord | None = None

    def submit(self, job: RealRunJob, now: datetime) -> RealRunResponse:
        current = _utc(now)
        validate_real_run_approval(job, current)
        if job.run_id in self._records:
            raise MockRealRunError("run_id has already been submitted")
        if job.approval.approval_id in self._used_approvals:
            raise MockRealRunError("approval has already been used")
        if job.profile_id not in self.policy.allowed_profiles:
            raise MockRealRunError("profile is not allowed")
        if job.test_cases[0] not in self.policy.allowed_test_cases:
            raise MockRealRunError("test case is not allowed")
        self._expire_lock(current)
        if self._active_lock is not None:
            raise MockRealRunError("instrument lock is busy")

        self._used_approvals.add(job.approval.approval_id)
        record = _MockRecord(
            job=job,
            state=RealRunState.QUEUED,
            submitted_at=current,
            deadline=current + timedelta(seconds=job.duration_seconds),
            lock_id=f"lock-{secrets.token_hex(8)}",
            context_id=f"ctx-{secrets.token_hex(8)}",
            a2a_task_id=f"task-{secrets.token_hex(8)}",
            audit_id=f"audit-{secrets.token_hex(8)}",
        )
        self._records[job.run_id] = record
        self._active_lock = record
        return self._response(record)

    def cancel(self, run_id: str, now: datetime, reason: str = "operator_requested") -> RealRunResponse:
        record = self._get(run_id)
        if record.state in {RealRunState.COMPLETED, RealRunState.FAILED, RealRunState.CANCELED}:
            raise MockRealRunError("run is already terminal")
        record.state = RealRunState.CANCELED
        record.reason = reason
        self._release_lock(record)
        return self._response(record)

    def timeout_due_runs(self, now: datetime) -> list[RealRunResponse]:
        current = _utc(now)
        results = []
        for record in self._records.values():
            if record.state in {RealRunState.QUEUED, RealRunState.RUNNING, RealRunState.COLLECTING, RealRunState.INGESTING} and current >= record.deadline:
                record.state = RealRunState.CANCELED
                record.reason = "timeout_safe_state_required"
                self._release_lock(record)
                results.append(self._response(record))
        return results

    def complete(self, run_id: str, artifact_bytes: bytes, ingest_task_id: str) -> RealRunResponse:
        record = self._get(run_id)
        if record.state not in {RealRunState.QUEUED, RealRunState.RUNNING, RealRunState.COLLECTING, RealRunState.INGESTING}:
            raise MockRealRunError("run is not executable")
        if not artifact_bytes:
            raise MockRealRunError("artifact must not be empty")
        if len(artifact_bytes) > record.job.artifact_policy.max_size_bytes:
            raise MockRealRunError("artifact exceeds configured size")
        record.artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        record.ingest_task_id = ingest_task_id
        record.state = RealRunState.COMPLETED
        self._release_lock(record)
        return self._response(record)

    def status(self, run_id: str) -> RealRunResponse:
        return self._response(self._get(run_id))

    def _get(self, run_id: str) -> _MockRecord:
        try:
            return self._records[run_id]
        except KeyError as exc:
            raise MockRealRunError("unknown run_id") from exc

    def _expire_lock(self, now: datetime) -> None:
        if self._active_lock is not None:
            lock_expiry = self._active_lock.submitted_at + timedelta(seconds=self.policy.lock_lease_seconds)
            if now >= lock_expiry:
                self._active_lock.reason = "lock_lease_expired"
                self._active_lock.state = RealRunState.CANCELED
                self._active_lock = None

    def _release_lock(self, record: _MockRecord) -> None:
        if self._active_lock is record:
            self._active_lock = None

    @staticmethod
    def _response(record: _MockRecord) -> RealRunResponse:
        state = record.state
        if state is RealRunState.COMPLETED:
            test_status = report_status = ingest_status = "completed"
        elif state is RealRunState.CANCELED:
            test_status = report_status = ingest_status = "canceled"
        else:
            test_status = report_status = ingest_status = "pending"
        return RealRunResponse(
            state=state,
            correlation=RealRunCorrelation(
                run_id=record.job.run_id,
                context_id=record.context_id,
                a2a_task_id=record.a2a_task_id,
                approval_id=record.job.approval.approval_id,
                execution_owner="anritsu-openclaw",
                audit_id=record.audit_id,
                instrument_lock_id=record.lock_id,
                artifact_sha256=record.artifact_sha256,
                ingest_task_id=record.ingest_task_id,
            ),
            test_status=test_status,
            report_status=report_status,
            ingest_status=ingest_status,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("runtime timestamps must include a timezone")
    return value.astimezone(timezone.utc)
