from __future__ import annotations

import tempfile

import pytest

from src.test_reports.csit_boundary import CSITBoundaryError, validate_csit_metadata
from src.test_reports.registry import SubmissionRegistry


def csit(**changes: str) -> dict[str, str]:
    value = {
        "source_record_id": "CSIT-TR-001",
        "approval_status": "approved",
        "revision": "2",
        "correlation_id": "corr-001",
    }
    value.update(changes)
    return value


def test_csit_contract_requires_complete_decision():
    assert validate_csit_metadata(csit())["source_record_id"] == "CSIT-TR-001"
    assert validate_csit_metadata({}) == {}
    with pytest.raises(CSITBoundaryError):
        validate_csit_metadata(csit(correlation_id=""))
    with pytest.raises(CSITBoundaryError):
        validate_csit_metadata(csit(approval_status="escalated"))


def test_registry_persists_csit_owner_and_separate_km_validation_state():
    with tempfile.TemporaryDirectory() as directory:
        registry = SubmissionRegistry(f"sqlite:///{directory}/registry.sqlite3")
        item, duplicate = registry.create({
            "submission_id": "submission-1",
            "environment": "anritsu",
            "run_id": "RUN-001",
            "agent_id": "agent-1",
            "report_name": "report.xlsx",
            "report_hash": "a" * 64,
            "original_path": "/tmp/report.xlsx",
            "manifest": {"run_id": "RUN-001", "csit": csit()},
            "validation": {"valid": True},
            "csit_source_record_id": "CSIT-TR-001",
            "csit_approval_status": "approved",
            "csit_revision": "2",
            "csit_correlation_id": "corr-001",
        })
        assert duplicate is False
        assert item["csit_source_record_id"] == "CSIT-TR-001"
        assert item["csit_approval_status"] == "approved"
        assert item["km_validation_status"] == "pending"

        validated = registry.transition(
            "submission-1", {"pending_review"}, "approved", km_validation_status="validated"
        )
        assert validated["csit_approval_status"] == "approved"
        assert validated["km_validation_status"] == "validated"


def test_rejected_csit_state_is_not_a_reviewable_km_submission():
    with tempfile.TemporaryDirectory() as directory:
        registry = SubmissionRegistry(f"sqlite:///{directory}/registry.sqlite3")
        item, _ = registry.create({
            "submission_id": "submission-rejected",
            "environment": "anritsu",
            "run_id": "RUN-REJECTED",
            "agent_id": "agent-1",
            "report_name": "report.xlsx",
            "report_hash": "b" * 64,
            "original_path": "/tmp/report.xlsx",
            "manifest": {"run_id": "RUN-REJECTED", "csit": csit(approval_status="rejected")},
            "validation": {"valid": True},
            "status": "rejected",
            "csit_source_record_id": "CSIT-TR-001",
            "csit_approval_status": "rejected",
            "csit_revision": "2",
            "csit_correlation_id": "corr-001",
        })
        assert item["status"] == "rejected"
