"""Contracts for the knowledge-management A2A bridge."""

from .config import BridgeConfig
from .contracts import (
    A2ATaskCorrelation,
    A2ATaskState,
    Correlation,
    BridgeDispatchError,
    IngestStatus,
    RejectionReason,
    RunStatus,
    TestJob,
    TaskRecord,
    TestStatus,
    ReportStatus,
    validate_dispatch,
)

__all__ = [
    "A2ATaskCorrelation", "A2ATaskState", "Correlation", "BridgeConfig", "BridgeDispatchError", "IngestStatus",
    "RejectionReason", "RunStatus", "TestJob", "TestStatus", "ReportStatus",
    "TaskRecord", "validate_dispatch",
]
