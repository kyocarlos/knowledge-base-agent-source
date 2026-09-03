"""Durable submission/audit registry with PostgreSQL and SQLite test fallback."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


FINAL_STATUSES = {"validation_failed", "rejected", "completed", "ingest_failed"}


class SubmissionConflict(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SubmissionRegistry:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv(
            "KB_REPORT_REGISTRY_URL", "sqlite:////app/data/report-submissions.sqlite3"
        )
        self.is_postgres = self.database_url.startswith(("postgresql://", "postgres://"))
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if self.is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:
                raise RuntimeError("PostgreSQL registry 需要 psycopg 套件") from exc
            with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
                yield connection
            return
        raw_path = self.database_url.removeprefix("sqlite:///")
        path = Path(raw_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.is_postgres else statement

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute(self._sql("""
                CREATE TABLE IF NOT EXISTS report_submissions (
                    submission_id TEXT PRIMARY KEY,
                    environment TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    report_name TEXT NOT NULL,
                    report_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    original_path TEXT NOT NULL,
                    attachments_json TEXT NOT NULL,
                    manifest_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    reviewer_id TEXT,
                    review_comment TEXT,
                    reviewed_at TEXT,
                    csit_source_record_id TEXT,
                    csit_approval_status TEXT,
                    csit_revision TEXT,
                    csit_correlation_id TEXT,
                    km_validation_status TEXT NOT NULL DEFAULT 'pending',
                    ingest_task_id TEXT,
                    error TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(environment, run_id)
                )
            """))
            for column, definition in (
                ("csit_source_record_id", "TEXT"),
                ("csit_approval_status", "TEXT"),
                ("csit_revision", "TEXT"),
                ("csit_correlation_id", "TEXT"),
                ("km_validation_status", "TEXT NOT NULL DEFAULT 'pending'"),
            ):
                savepoint = f"km005_{column}"
                try:
                    connection.execute(self._sql(f"SAVEPOINT {savepoint}"))
                    connection.execute(self._sql(
                        f"ALTER TABLE report_submissions ADD COLUMN {column} {definition}"
                    ))
                    connection.execute(self._sql(f"RELEASE SAVEPOINT {savepoint}"))
                except Exception:
                    connection.execute(self._sql(f"ROLLBACK TO SAVEPOINT {savepoint}"))
                    connection.execute(self._sql(f"RELEASE SAVEPOINT {savepoint}"))

    @staticmethod
    def _decode(row: Any | None) -> dict | None:
        if row is None:
            return None
        item = dict(row)
        for field in ("attachments_json", "manifest_json", "validation_json"):
            value = item.pop(field, "{}")
            item[field.removesuffix("_json")] = json.loads(value or "{}")
        return item

    def get(self, submission_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                self._sql("SELECT * FROM report_submissions WHERE submission_id = ?"),
                (submission_id,),
            ).fetchone()
        return self._decode(row)

    def find_by_run(self, environment: str, run_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(
                self._sql("SELECT * FROM report_submissions WHERE environment = ? AND run_id = ?"),
                (environment, run_id),
            ).fetchone()
        return self._decode(row)

    def find_by_run_any_environment(self, run_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                self._sql("SELECT * FROM report_submissions WHERE run_id = ? ORDER BY created_at DESC"),
                (run_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def delete_by_submission_id(self, submission_id: str, run_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                self._sql("DELETE FROM report_submissions WHERE submission_id = ? AND run_id = ?"),
                (submission_id, run_id),
            )
        return cursor.rowcount == 1

    def create(self, item: dict) -> tuple[dict, bool]:
        existing = self.find_by_run(item["environment"], item["run_id"])
        if existing:
            if existing["report_hash"] == item["report_hash"]:
                return existing, True
            raise SubmissionConflict("相同 environment/run_id 已存在不同內容")
        now = _now()
        values = (
            item["submission_id"], item["environment"], item["run_id"], item["agent_id"],
            item["report_name"], item["report_hash"], item.get("status", "pending_review"),
            item["original_path"], json.dumps(item.get("attachments", []), ensure_ascii=False),
            json.dumps(item.get("manifest", {}), ensure_ascii=False),
            json.dumps(item.get("validation", {}), ensure_ascii=False),
            item.get("csit_source_record_id"), item.get("csit_approval_status"),
            item.get("csit_revision"), item.get("csit_correlation_id"),
            item.get("km_validation_status", "pending"), now, now,
        )
        try:
            with self._connection() as connection:
                connection.execute(self._sql("""
                    INSERT INTO report_submissions (
                        submission_id, environment, run_id, agent_id, report_name, report_hash,
                        status, original_path, attachments_json, manifest_json, validation_json,
                        csit_source_record_id, csit_approval_status, csit_revision,
                        csit_correlation_id, km_validation_status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """), values)
        except Exception:
            existing = self.find_by_run(item["environment"], item["run_id"])
            if existing and existing["report_hash"] == item["report_hash"]:
                return existing, True
            raise
        return self.get(item["submission_id"]), False

    def list(self, status: str | None = None, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        sql = "SELECT * FROM report_submissions"
        params: list[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connection() as connection:
            rows = connection.execute(self._sql(sql), tuple(params)).fetchall()
        return [self._decode(row) for row in rows]

    def transition(self, submission_id: str, expected: set[str], status: str, **changes: Any) -> dict:
        current = self.get(submission_id)
        if not current:
            raise KeyError(submission_id)
        if current["status"] not in expected:
            raise SubmissionConflict(f"狀態已變更，目前為 {current['status']}")
        fields = {"status": status, "updated_at": _now(), "version": current["version"] + 1, **changes}
        assignments = ", ".join(f"{field} = ?" for field in fields)
        params = list(fields.values()) + [submission_id, current["version"]]
        with self._connection() as connection:
            cursor = connection.execute(
                self._sql(f"UPDATE report_submissions SET {assignments} WHERE submission_id = ? AND version = ?"),
                tuple(params),
            )
            if cursor.rowcount != 1:
                raise SubmissionConflict("報告已被其他審核者更新")
        return self.get(submission_id)

    def sync_ingest_status(self, submission_id: str, task_state: dict) -> dict:
        status = task_state.get("status")
        mapped = "completed" if status == "completed" else "ingest_failed" if status == "failed" else status
        current = self.get(submission_id)
        if not current or current["status"] in {"rejected", "validation_failed"}:
            return current
        return self.transition(
            submission_id,
            {current["status"]},
            mapped or current["status"],
            error=task_state.get("error"),
        )
