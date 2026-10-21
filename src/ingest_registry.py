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
            connection.execute("""
                CREATE TABLE IF NOT EXISTS package_revisions (
                    package_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    document_version TEXT NOT NULL,
                    content_hash TEXT NOT NULL DEFAULT '',
                    publish_status TEXT NOT NULL,
                    is_current INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(document_id, document_version),
                    CHECK (publish_status IN ('draft', 'ready', 'published', 'superseded')),
                    CHECK (is_current IN (0, 1)),
                    CHECK (is_current = 0 OR publish_status = 'published')
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS csit_pull_sources (
                    document_id TEXT NOT NULL,
                    file_id TEXT NOT NULL,
                    document_version TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    ingested_at TEXT,
                    status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, file_id, document_version)
                )
            """)

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

    def register_package_revision(
        self,
        *,
        package_id: str,
        document_id: str,
        document_version: str,
        content_hash: str = "",
    ) -> dict:
        """Register an immutable draft revision idempotently."""
        now = _now()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM package_revisions WHERE package_id = ?",
                (package_id,),
            ).fetchone()
            if row:
                existing = dict(row)
                if (existing["document_id"], existing["document_version"], existing["content_hash"]) != (
                    document_id, document_version, content_hash
                ):
                    connection.execute("ROLLBACK")
                    raise IngestRegistryConflict(
                        "package_conflict",
                        "package_id 已對應不同 revision identity",
                        existing,
                    )
                connection.execute("COMMIT")
                return existing
            try:
                connection.execute(
                    """
                    INSERT INTO package_revisions
                        (package_id, document_id, document_version, content_hash,
                         publish_status, is_current, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 'draft', 0, ?, ?)
                    """,
                    (package_id, document_id, document_version, content_hash, now, now),
                )
            except sqlite3.IntegrityError:
                connection.execute("ROLLBACK")
                existing = connection.execute(
                    "SELECT * FROM package_revisions WHERE document_id = ? AND document_version = ?",
                    (document_id, document_version),
                ).fetchone()
                raise IngestRegistryConflict(
                    "package_revision_conflict",
                    "document revision 已存在不同 package_id",
                    self._decode(existing),
                )
            connection.execute("COMMIT")
        return {
            "package_id": package_id,
            "document_id": document_id,
            "document_version": document_version,
            "content_hash": content_hash,
            "publish_status": "draft",
            "is_current": 0,
            "created_at": now,
            "updated_at": now,
        }

    def find_package_revision(self, package_id: str) -> dict | None:
        with self._connection() as connection:
            return self._decode(connection.execute(
                "SELECT * FROM package_revisions WHERE package_id = ?", (package_id,)
            ).fetchone())

    def list_package_revisions(self, document_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM package_revisions WHERE document_id = ? ORDER BY document_version",
                (document_id,),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def mark_package_ready(self, package_id: str) -> dict:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM package_revisions WHERE package_id = ?", (package_id,)
            ).fetchone()
            if not row:
                connection.execute("ROLLBACK")
                raise IngestRegistryConflict("package_not_found", "package revision 不存在")
            if row["publish_status"] != "draft":
                connection.execute("ROLLBACK")
                raise IngestRegistryConflict("invalid_package_transition", "只有 draft 可轉為 ready", dict(row))
            connection.execute(
                "UPDATE package_revisions SET publish_status = 'ready', updated_at = ? WHERE package_id = ?",
                (_now(), package_id),
            )
            updated = connection.execute(
                "SELECT * FROM package_revisions WHERE package_id = ?", (package_id,)
            ).fetchone()
            connection.execute("COMMIT")
        return dict(updated)

    def publish_package_revision(self, package_id: str, *, is_current: bool = True) -> dict:
        """Publish one ready revision, optionally making it current."""
        if not isinstance(is_current, bool):
            raise ValueError("is_current must be boolean")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            target = connection.execute(
                "SELECT * FROM package_revisions WHERE package_id = ?", (package_id,)
            ).fetchone()
            if not target:
                connection.execute("ROLLBACK")
                raise IngestRegistryConflict("package_not_found", "package revision 不存在")
            if target["publish_status"] != "ready":
                connection.execute("ROLLBACK")
                raise IngestRegistryConflict("invalid_package_transition", "只有 ready 可發布", dict(target))
            now = _now()
            if is_current:
                connection.execute(
                    """
                    UPDATE package_revisions
                    SET publish_status = 'superseded', is_current = 0, updated_at = ?
                    WHERE document_id = ? AND is_current = 1
                    """,
                    (now, target["document_id"]),
                )
            connection.execute(
                """
                UPDATE package_revisions
                SET publish_status = 'published', is_current = 1, updated_at = ?
                WHERE package_id = ?
                """,
                (now, package_id),
            )
            if not is_current:
                connection.execute(
                    "UPDATE package_revisions SET is_current = 0 WHERE package_id = ?",
                    (package_id,),
                )
            published = connection.execute(
                "SELECT * FROM package_revisions WHERE package_id = ?", (package_id,)
            ).fetchone()
            connection.execute("COMMIT")
        return dict(published)

    def record_event(self, event_type: str, task_id: str | None = None, **details) -> None:
        safe_details = {key: value for key, value in details.items() if key.lower() not in {"authorization", "token", "password", "secret"}}
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO ingestion_events (task_id, event_type, details_json, created_at) VALUES (?, ?, ?, ?)",
                (task_id, event_type, json.dumps(safe_details, ensure_ascii=False, default=str), _now()),
            )

    def record_csit_pull(
        self,
        *,
        document_id: str,
        file_id: str,
        document_version: str,
        sha256: str,
        status: str,
        error: str = "",
    ) -> dict:
        """Track CSIT Pull identity without treating absence as withdrawal."""
        if status not in {"discovered", "downloaded", "ingested", "failed"}:
            raise ValueError("unsupported CSIT Pull status")
        now = _now()
        ingested_at = now if status == "ingested" else None
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO csit_pull_sources
                    (document_id, file_id, document_version, sha256, ingested_at,
                     status, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id, file_id, document_version) DO UPDATE SET
                    sha256=excluded.sha256,
                    ingested_at=COALESCE(excluded.ingested_at, csit_pull_sources.ingested_at),
                    status=excluded.status,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (document_id, file_id, document_version, sha256, ingested_at, status, str(error)[:1000], now),
            )
            row = connection.execute(
                """
                SELECT * FROM csit_pull_sources
                WHERE document_id = ? AND file_id = ? AND document_version = ?
                """,
                (document_id, file_id, document_version),
            ).fetchone()
        return dict(row)

    def find_csit_pull(self, document_id: str, file_id: str, document_version: str) -> dict | None:
        with self._connection() as connection:
            return self._decode(connection.execute(
                """
                SELECT * FROM csit_pull_sources
                WHERE document_id = ? AND file_id = ? AND document_version = ?
                """,
                (document_id, file_id, document_version),
            ).fetchone())
