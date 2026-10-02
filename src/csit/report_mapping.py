"""Map CSIT report/file identity into existing KM source metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class CsitMetadataError(ValueError):
    """Raised when required CSIT provenance is missing or ambiguous."""


def _required(value: object, name: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise CsitMetadataError(f"CSIT metadata requires {name}")
    return result


@dataclass(frozen=True, slots=True)
class CsitReportSource:
    """Identity returned by CSIT and consumed by the existing KM ingest path."""

    report_id: str
    file_id: str
    task_id: str
    case_id: str
    record_id: str
    version: str
    approval_status: str
    correlation_id: str
    test_run_id: str | None = None

    @classmethod
    def from_csit(cls, value: dict[str, Any]) -> "CsitReportSource":
        required_keys = (
            "report_id", "file_id", "task_id", "case_id", "record_id",
            "version", "approval_status", "correlation_id",
        )
        normalized = {key: _required(value.get(key), key) for key in required_keys}
        test_run_id = str(value.get("test_run_id") or "").strip() or None
        return cls(**normalized, test_run_id=test_run_id)

    def to_source_metadata(self, *, file_name: str) -> dict[str, str]:
        """Return sidecar fields; approval is preserved, never promoted by KM."""

        name = _required(file_name, "file_name")
        metadata = {
            "source_system": "CSIT",
            "source_record_id": self.report_id,
            "source_file_id": self.file_id,
            "csit_report_id": self.report_id,
            "csit_file_id": self.file_id,
            "csit_task_id": self.task_id,
            "csit_case_id": self.case_id,
            "csit_record_id": self.record_id,
            "document_id": self.report_id,
            "document_version": self.version,
            "approval_status": self.approval_status,
            "correlation_id": self.correlation_id,
            "artifact_type": "test_report",
            "source_file_name": name,
        }
        if self.test_run_id:
            metadata["run_id"] = self.test_run_id
            metadata["test_run_id"] = self.test_run_id
        return metadata
