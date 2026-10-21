"""Deterministic orchestration for dispatching one test job."""

from __future__ import annotations

from .config import BridgeConfig
from .contracts import A2ATaskState, TaskRecord, TestJob, validate_dispatch
from .journal import JournalConflict, TaskJournal
from .transport import A2ATransport, TransportRejected


class BridgeService:
    def __init__(self, config: BridgeConfig, journal: TaskJournal, transport: A2ATransport):
        self.config = config
        self.journal = journal
        self.transport = transport

    async def submit(self, job: TestJob) -> tuple[TaskRecord, bool]:
        validate_dispatch(self.config, job)
        record, duplicate = self.journal.create(job)
        if duplicate:
            return record, True
        record = self.journal.update(record.task_key, state=A2ATaskState.QUEUED)
        try:
            result = await self.transport.dispatch(
                self.config.agent_endpoints[job.environment],
                self.config.agent_credentials[job.environment],
                job,
            )
        except TransportRejected as exc:
            return self.journal.update(
                record.task_key,
                state=A2ATaskState.REJECTED,
                rejection_reason=exc.reason,
                error_message=str(exc),
            ), False
        except Exception as exc:
            return self.journal.update(
                record.task_key,
                state=A2ATaskState.FAILED,
                error_message=f"transport failure: {type(exc).__name__}",
            ), False
        return self.journal.update(
            record.task_key,
            state=result.state,
            correlation=result.correlation,
            status=result.status,
        ), False


__all__ = ["BridgeService", "JournalConflict"]
