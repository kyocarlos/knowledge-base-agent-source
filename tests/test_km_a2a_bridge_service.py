from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from km_a2a_bridge import (
    A2ATaskState,
    BridgeConfig,
    IngestStatus,
    RejectionReason,
    ReportStatus,
    TestJob as JobContract,
    TestStatus as JobTestStatus,
)
from km_a2a_bridge.journal import JournalConflict, TaskJournal
from km_a2a_bridge.service import BridgeService
from km_a2a_bridge.transport import MockA2ATransport

CONTROL_HASH = "a" * 64


def config() -> BridgeConfig:
    return BridgeConfig(
        enabled=True,
        control_token_sha256=CONTROL_HASH,
        allowed_profiles={"anritsu": {"safe-profile"}},
        agent_endpoints={"anritsu": "https://anritsu.example"},
        agent_credentials={"anritsu": "a2a-only-secret"},
    )


def job(**changes) -> JobContract:
    values = {
        "job_type": "run_iperf_test",
        "environment": "anritsu",
        "profile_id": "safe-profile",
        "run_id": "run-001",
        "requested_by": "operator-1",
        "duration_seconds": 60,
        "test_cases": ["sa_dl_tcp"],
    }
    values.update(changes)
    return JobContract(**values)


def test_mock_dispatch_persists_correlation_without_faking_business_completion(tmp_path):
    transport = MockA2ATransport()
    service = BridgeService(config(), TaskJournal(tmp_path / "tasks.sqlite3"), transport)
    record, duplicate = asyncio.run(service.submit(job()))
    assert duplicate is False
    assert record.state is A2ATaskState.COMPLETED
    assert record.correlation.context_id
    assert record.correlation.a2a_task_id
    assert record.correlation.run_id == "run-001"
    assert record.correlation.ingest_task_id is None
    assert record.status.test_status is JobTestStatus.PENDING
    assert record.status.report_status is ReportStatus.PENDING
    assert record.status.ingest_status is IngestStatus.PENDING


def test_duplicate_submission_returns_original_without_second_transport_call(tmp_path):
    transport = MockA2ATransport()
    service = BridgeService(config(), TaskJournal(tmp_path / "tasks.sqlite3"), transport)
    first, first_duplicate = asyncio.run(service.submit(job()))
    second, second_duplicate = asyncio.run(service.submit(job()))
    assert first_duplicate is False
    assert second_duplicate is True
    assert second == first
    assert transport.calls == 1


def test_same_run_with_different_payload_is_a_conflict(tmp_path):
    service = BridgeService(config(), TaskJournal(tmp_path / "tasks.sqlite3"), MockA2ATransport())
    asyncio.run(service.submit(job()))
    with pytest.raises(JournalConflict):
        asyncio.run(service.submit(job(duration_seconds=120)))


@pytest.mark.parametrize("reason", [RejectionReason.BUSY, RejectionReason.CAPACITY_EXCEEDED])
def test_transport_rejection_is_persisted_with_stable_reason(tmp_path, reason):
    service = BridgeService(
        config(),
        TaskJournal(tmp_path / "tasks.sqlite3"),
        MockA2ATransport(rejection=reason),
    )
    record, duplicate = asyncio.run(service.submit(job()))
    assert duplicate is False
    assert record.state is A2ATaskState.REJECTED
    assert record.rejection_reason is reason


def test_journal_survives_new_instance(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    service = BridgeService(config(), TaskJournal(path), MockA2ATransport())
    record, _ = asyncio.run(service.submit(job()))
    restored = TaskJournal(path).get(record.task_key)
    assert restored == record


def test_concurrent_identical_journal_creates_are_idempotent(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    task_journal = TaskJournal(path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: task_journal.create(job()), range(8)))
    assert sum(1 for _, duplicate in results if not duplicate) == 1
    assert len({record.task_key for record, _ in results}) == 1
