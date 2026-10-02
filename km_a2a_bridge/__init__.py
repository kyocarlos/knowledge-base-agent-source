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
from .real_contracts import (
    RealArtifactPolicy,
    RealRunApproval,
    RealRunCorrelation,
    RealRunJob,
    RealRunResponse,
    RealRunState,
    validate_real_run_approval,
)
from .mock_real_runtime import MockRealRunController, MockRealRunError, MockRealRunPolicy
from .anritsu_shadow_adapter import (
    MockAnritsuOpenClawAdapter,
    ShadowAdapterRequest,
    ShadowAdapterResponse,
    ShadowSideEffectCounts,
)

__all__ = [
    "A2ATaskCorrelation", "A2ATaskState", "Correlation", "BridgeConfig", "BridgeDispatchError", "IngestStatus",
    "RejectionReason", "RunStatus", "TestJob", "TestStatus", "ReportStatus",
    "TaskRecord", "validate_dispatch",
    "RealArtifactPolicy", "RealRunApproval", "RealRunCorrelation", "RealRunJob",
    "RealRunResponse", "RealRunState", "validate_real_run_approval",
    "MockRealRunController", "MockRealRunError", "MockRealRunPolicy",
    "MockAnritsuOpenClawAdapter", "ShadowAdapterRequest", "ShadowAdapterResponse",
    "ShadowSideEffectCounts",
]
