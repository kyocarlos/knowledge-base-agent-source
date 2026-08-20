"""Durable application-level job leases independent of broker redelivery."""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def _database_path() -> Path:
    return Path(os.getenv("KB_JOB_LEDGER_PATH", "data/job-ledger.sqlite3"))


class JobLeaseStore:
    def __init__(self, database_path: str | Path | None = None):
        self.database_path = Path(database_path) if database_path else _database_path()
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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_leases (
                    job_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    owner TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    lease_until REAL NOT NULL DEFAULT 0,
                    recovery_count INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )

    def register(self, job_id: str, idempotency_key: str | None = None) -> dict:
        if not job_id:
            raise ValueError("job_id is required")
        key = idempotency_key or job_id
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT * FROM job_leases WHERE job_id = ?", (job_id,)).fetchone()
            if existing:
                if existing["idempotency_key"] != key:
                    raise ValueError("job_id already has a different idempotency_key")
                connection.execute("COMMIT")
                return dict(existing)
            connection.execute(
                "INSERT INTO job_leases (job_id, idempotency_key, status, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?)",
                (job_id, key, now, now),
            )
            connection.execute("COMMIT")
        return self.get(job_id) or {}

    def get(self, job_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM job_leases WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def claim(self, job_id: str, owner: str, lease_seconds: int = 600) -> dict | None:
        if not owner or lease_seconds < 1:
            raise ValueError("owner and positive lease_seconds are required")
        now = time.time()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM job_leases WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                connection.execute("ROLLBACK")
                return None
            if row["status"] == "succeeded":
                connection.execute("COMMIT")
                return None
            if row["status"] == "running" and row["lease_until"] > now and row["owner"] != owner:
                connection.execute("COMMIT")
                return None
            connection.execute(
                """
                UPDATE job_leases
                SET status='running', owner=?, attempt=attempt+1,
                    lease_until=?, updated_at=?
                WHERE job_id=?
                """,
                (owner, now + lease_seconds, now, job_id),
            )
            connection.execute("COMMIT")
        return self.get(job_id)

    def heartbeat(self, job_id: str, owner: str, lease_seconds: int = 600) -> bool:
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE job_leases SET lease_until=?, updated_at=? WHERE job_id=? AND owner=? AND status='running'",
                (now + lease_seconds, now, job_id, owner),
            )
        return cursor.rowcount == 1

    def complete(self, job_id: str, owner: str) -> bool:
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE job_leases SET status='succeeded', owner=NULL, lease_until=0, completed_at=?, updated_at=? WHERE job_id=? AND owner=? AND status='running'",
                (now, now, job_id, owner),
            )
        return cursor.rowcount == 1

    def mark_retrying(self, job_id: str, owner: str) -> bool:
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE job_leases SET status='retrying', owner=NULL, lease_until=0, updated_at=? WHERE job_id=? AND owner=? AND status='running'",
                (now, job_id, owner),
            )
        return cursor.rowcount == 1

    def fail(self, job_id: str, owner: str) -> bool:
        now = time.time()
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE job_leases SET status='failed', owner=NULL, lease_until=0, updated_at=? WHERE job_id=? AND owner=? AND status='running'",
                (now, job_id, owner),
            )
        return cursor.rowcount == 1

    def recover_expired(self, now: float | None = None) -> list[str]:
        current = time.time() if now is None else now
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                "SELECT job_id FROM job_leases WHERE status='running' AND lease_until <= ?", (current,)
            ).fetchall()
            job_ids = [row["job_id"] for row in rows]
            if job_ids:
                connection.executemany(
                    "UPDATE job_leases SET status='queued', owner=NULL, lease_until=0, recovery_count=recovery_count+1, updated_at=? WHERE job_id=? AND status='running' AND lease_until <= ?",
                    [(current, job_id, current) for job_id in job_ids],
                )
            connection.execute("COMMIT")
        return job_ids
