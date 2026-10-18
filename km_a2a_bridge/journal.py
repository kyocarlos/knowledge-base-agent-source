"""SQLite task journal owned only by the isolated A2A bridge."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .contracts import A2ATaskCorrelation, A2ATaskState, RunStatus, TaskRecord, TestJob


class JournalConflict(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskJournal:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS a2a_tasks (
                    task_key TEXT PRIMARY KEY,
                    environment TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    job_json TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    UNIQUE(environment, run_id)
                )
                """
            )

    def create(self, job: TestJob) -> tuple[TaskRecord, bool]:
        job_json = job.model_dump_json()
        task_key = f"{job.environment}:{job.run_id}"
        timestamp = _now()
        record = TaskRecord(
            task_key=task_key,
            job=job,
            correlation=A2ATaskCorrelation(run_id=job.run_id),
            created_at=timestamp,
            updated_at=timestamp,
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    "INSERT INTO a2a_tasks(task_key, environment, run_id, job_json, record_json) VALUES(?,?,?,?,?)",
                    (task_key, job.environment, job.run_id, job_json, record.model_dump_json()),
                )
            except sqlite3.IntegrityError:
                existing = connection.execute(
                    "SELECT job_json, record_json FROM a2a_tasks WHERE environment=? AND run_id=?",
                    (job.environment, job.run_id),
                ).fetchone()
                if existing is None:
                    raise
                if existing["job_json"] != job_json:
                    raise JournalConflict("same environment/run_id has a different job payload")
                return TaskRecord.model_validate_json(existing["record_json"]), True
        return record, False

    def get(self, task_key: str) -> TaskRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM a2a_tasks WHERE task_key=?", (task_key,)
            ).fetchone()
        return TaskRecord.model_validate_json(row["record_json"]) if row else None

    def update(
        self,
        task_key: str,
        *,
        state: A2ATaskState | None = None,
        correlation: A2ATaskCorrelation | None = None,
        status: RunStatus | None = None,
        rejection_reason=None,
        error_message: str | None = None,
    ) -> TaskRecord:
        record = self.get(task_key)
        if record is None:
            raise KeyError(task_key)
        changes = {"updated_at": _now()}
        if state is not None:
            changes["state"] = state
        if correlation is not None:
            changes["correlation"] = correlation
        if status is not None:
            changes["status"] = status
        if rejection_reason is not None:
            changes["rejection_reason"] = rejection_reason
        if error_message is not None:
            changes["error_message"] = error_message
        updated = record.model_copy(update=changes)
        with self._connect() as connection:
            connection.execute(
                "UPDATE a2a_tasks SET record_json=? WHERE task_key=?",
                (updated.model_dump_json(), task_key),
            )
        return updated
