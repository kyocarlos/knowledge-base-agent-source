"""Durable identity registry for conflict-safe ingestion submissions."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


class IngestRegistryConflict(RuntimeError):
    def __init__(self, code: str, message: str, existing: dict | None = None):
        self.code = code
        self.existing = existing or {}
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db_path() -> Path:
    configured = os.getenv("KB_INGEST_REGISTRY_URL", "sqlite:///data/ingestion-registry.sqlite3")
    if configured.startswith("sqlite:///"):
        return Path(configured.removeprefix("sqlite:///"))
    raise RuntimeError("KB_INGEST_REGISTRY_URL 目前僅支援 sqlite:/// 路徑")


class IngestRegistry:
    def __init__(self, database_path: str | Path | None = None):
        self.database_path = Path(database_path) if database_path else _db_path()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS ingestion_requests (
                    task_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    document_id TEXT NOT NULL UNIQUE,
                    source_system TEXT NOT NULL,
                    environment_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    artifact_type TEXT NOT NULL,
                    report_schema TEXT NOT NULL,
                    original_file_name TEXT NOT NULL,
                    source_file_hash TEXT NOT NULL,
                    ingest_file_hash TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS ingestion_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

    def initialize_knowledge_revisions(self) -> None:
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_revisions (
                    package_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    document_version TEXT NOT NULL,
                    publish_status TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS knowledge_revisions_current_idx "
                "ON knowledge_revisions(document_id) WHERE is_current = 1"
            )

    @staticmethod
    def _decode_revision(row: sqlite3.Row | None) -> dict | None:
        if not row:
            return None
        item = dict(row)
        item["is_current"] = bool(item["is_current"])
        return item

    def find_knowledge_revision(self, package_id: str) -> dict | None:
        self.initialize_knowledge_revisions()
        with self._connection() as connection:
            return self._decode_revision(connection.execute(
                "SELECT * FROM knowledge_revisions WHERE package_id = ?", (package_id,)
            ).fetchone())

    def find_current_knowledge_revision(self, document_id: str, exclude_package_id: str = "") -> dict | None:
        self.initialize_knowledge_revisions()
        with self._connection() as connection:
            return self._decode_revision(connection.execute(
                "SELECT * FROM knowledge_revisions WHERE document_id = ? AND is_current = 1 AND package_id != ?",
                (document_id, exclude_package_id),
            ).fetchone())

    def has_knowledge_revisions(self, document_id: str) -> bool:
        self.initialize_knowledge_revisions()
        with self._connection() as connection:
            row = connection.execute(
                "SELECT 1 FROM knowledge_revisions WHERE document_id = ? LIMIT 1", (document_id,)
            ).fetchone()
        return row is not None

    def register_knowledge_revision(self, metadata: dict) -> dict:
        self.initialize_knowledge_revisions()
        now = _now()
        record = {
            "package_id": str(metadata["package_id"]),
            "document_id": str(metadata["document_id"]),
            "document_version": str(metadata["document_version"]),
            "publish_status": str(metadata.get("publish_status") or "draft"),
            "is_current": 1 if metadata.get("is_current", False) else 0,
            "created_at": now,
            "updated_at": now,
        }
        if record["publish_status"] != "published" and record["is_current"]:
            raise ValueError("only published revisions can be current")
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO knowledge_revisions "
                "(package_id, document_id, document_version, publish_status, is_current, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(package_id) DO NOTHING",
                tuple(record.values()),
            )
        return self.find_knowledge_revision(record["package_id"]) or record

    def transition_knowledge_revision(self, package_id: str, target: str) -> dict:
        from .knowledge_lifecycle import ALLOWED_TRANSITIONS

        current = self.find_knowledge_revision(package_id)
        if not current or target not in ALLOWED_TRANSITIONS.get(current["publish_status"], set()):
            raise ValueError("invalid knowledge revision transition")
        with self._connection() as connection:
            connection.execute(
                "UPDATE knowledge_revisions SET publish_status = ?, updated_at = ? WHERE package_id = ?",
                (target, _now(), package_id),
            )
        return self.find_knowledge_revision(package_id)

    def publish_knowledge_revision(self, package_id: str, prior_package_id: str | None = None) -> dict:
        current = self.find_knowledge_revision(package_id)
        if not current or current["publish_status"] != "ready":
            raise ValueError("only ready revisions can be published")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if prior_package_id:
                connection.execute(
                    "UPDATE knowledge_revisions SET is_current = 0, updated_at = ? WHERE package_id = ?",
                    (_now(), prior_package_id),
                )
            connection.execute(
                "UPDATE knowledge_revisions SET publish_status = 'published', is_current = 1, updated_at = ? WHERE package_id = ?",
                (_now(), package_id),
            )
            connection.execute("COMMIT")
        return self.find_knowledge_revision(package_id)

    @staticmethod
    def _decode(row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row else None

    def find_by_idempotency(self, key: str) -> dict | None:
        with self._connection() as connection:
            return self._decode(connection.execute("SELECT * FROM ingestion_requests WHERE idempotency_key = ?", (key,)).fetchone())

    def find_by_document(self, document_id: str) -> dict | None:
        with self._connection() as connection:
            return self._decode(connection.execute("SELECT * FROM ingestion_requests WHERE document_id = ?", (document_id,)).fetchone())

    def find_by_task(self, task_id: str) -> dict | None:
        with self._connection() as connection:
            return self._decode(connection.execute("SELECT * FROM ingestion_requests WHERE task_id = ?", (task_id,)).fetchone())

    def find_by_run(self, run_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM ingestion_requests WHERE run_id = ? ORDER BY created_at DESC",
                (run_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def delete_by_run(self, run_id: str) -> int:
        with self._connection() as connection:
            connection.execute("DELETE FROM ingestion_events WHERE task_id IN (SELECT task_id FROM ingestion_requests WHERE run_id = ?)", (run_id,))
            cursor = connection.execute("DELETE FROM ingestion_requests WHERE run_id = ?", (run_id,))
        return cursor.rowcount

    def register(self, identity: dict, task_id: str) -> tuple[dict, bool]:
        existing = self.find_by_idempotency(identity["idempotency_key"])
        if existing:
            if existing["document_id"] == identity["document_id"] and existing["ingest_file_hash"] == identity["ingest_file_hash"]:
                return existing, True
            raise IngestRegistryConflict("idempotency_conflict", "Idempotency-Key 已對應不同文件身份", existing)
        existing = self.find_by_document(identity["document_id"])
        if existing:
            if existing["idempotency_key"] == identity["idempotency_key"]:
                return existing, True
            raise IngestRegistryConflict("document_conflict", "documentId 已存在不同內容，不允許覆蓋", existing)

        now = _now()
        record = {
            "task_id": task_id,
            **identity,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
        }
        columns = tuple(record)
        try:
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    f"INSERT INTO ingestion_requests ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                    tuple(record[column] for column in columns),
                )
                connection.execute("COMMIT")
        except sqlite3.IntegrityError:
            existing = self.find_by_idempotency(identity["idempotency_key"]) or self.find_by_document(identity["document_id"])
            if existing and existing["idempotency_key"] == identity["idempotency_key"] and existing["document_id"] == identity["document_id"]:
                return existing, True
            raise IngestRegistryConflict("registration_race", "攝入身份在競態期間已被其他請求註冊", existing)
        return record, False

    def update_status(self, task_id: str, status: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE ingestion_requests SET status = ?, updated_at = ? WHERE task_id = ?",
                (status, _now(), task_id),
            )

    def record_event(self, event_type: str, task_id: str | None = None, **details) -> None:
        safe_details = {key: value for key, value in details.items() if key.lower() not in {"authorization", "token", "password", "secret"}}
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO ingestion_events (task_id, event_type, details_json, created_at) VALUES (?, ?, ?, ?)",
                (task_id, event_type, json.dumps(safe_details, ensure_ascii=False, default=str), _now()),
            )
