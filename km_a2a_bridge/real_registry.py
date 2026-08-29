"""Durable R1 registry for real-run approvals and instrument leases.

The registry is intentionally not wired into the current bridge. It provides
atomic primitives for a later real-run service and never contacts an agent or
instrument by itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import secrets
import sqlite3
from pathlib import Path

from .real_contracts import RealRunApproval


class RealRegistryConflict(RuntimeError):
    """The requested approval or lock cannot be safely acquired."""


@dataclass(frozen=True)
class LockLease:
    resource: str
    lock_id: str
    run_id: str
    owner_id: str
    acquired_at: datetime
    expires_at: datetime


class RealRunRegistry:
    """SQLite-backed approval and single-flight lock registry."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS real_run_approvals (
                    approval_id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    operator_id TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    single_use INTEGER NOT NULL CHECK(single_use = 1),
                    used_at TEXT
                );
                CREATE TABLE IF NOT EXISTS real_run_locks (
                    resource TEXT PRIMARY KEY,
                    lock_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL UNIQUE,
                    owner_id TEXT NOT NULL,
                    acquired_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                """
            )

    def register_approval(self, approval: RealRunApproval) -> None:
        values = (
            approval.approval_id,
            approval.run_id,
            approval.operator_id,
            _iso(approval.issued_at),
            _iso(approval.expires_at),
            1,
        )
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO real_run_approvals
                    (approval_id, run_id, operator_id, issued_at, expires_at, single_use)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
            except sqlite3.IntegrityError as exc:
                existing = connection.execute(
                    "SELECT run_id, operator_id, issued_at, expires_at FROM real_run_approvals WHERE approval_id=?",
                    (approval.approval_id,),
                ).fetchone()
                if existing is None or tuple(existing) != values[1:5]:
                    raise RealRegistryConflict("approval_id already exists with different data") from exc

    def consume_approval(self, approval: RealRunApproval, now: datetime) -> None:
        current = _utc(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT run_id, operator_id, expires_at, used_at FROM real_run_approvals WHERE approval_id=?",
                (approval.approval_id,),
            ).fetchone()
            if row is None:
                connection.rollback()
                raise RealRegistryConflict("approval is not registered")
            if row["run_id"] != approval.run_id or row["operator_id"] != approval.operator_id:
                connection.rollback()
                raise RealRegistryConflict("approval binding does not match")
            if row["used_at"] is not None:
                connection.rollback()
                raise RealRegistryConflict("approval has already been used")
            if _parse(row["expires_at"]) <= current:
                connection.rollback()
                raise RealRegistryConflict("approval has expired")
            connection.execute(
                "UPDATE real_run_approvals SET used_at=? WHERE approval_id=? AND used_at IS NULL",
                (_iso(current), approval.approval_id),
            )
            connection.commit()

    def acquire_lock(self, resource: str, run_id: str, owner_id: str, lease_seconds: int, now: datetime) -> LockLease:
        if not resource or not run_id or not owner_id or lease_seconds < 1:
            raise ValueError("resource, run_id, owner_id and positive lease_seconds are required")
        acquired = _utc(now)
        expires = acquired + timedelta(seconds=lease_seconds)
        lock = LockLease(resource, f"lock-{secrets.token_hex(8)}", run_id, owner_id, acquired, expires)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM real_run_locks WHERE expires_at <= ?", (_iso(acquired),))
            existing = connection.execute(
                "SELECT lock_id FROM real_run_locks WHERE resource=?", (resource,)
            ).fetchone()
            if existing is not None:
                connection.rollback()
                raise RealRegistryConflict("resource lock is busy")
            try:
                connection.execute(
                    """
                    INSERT INTO real_run_locks
                    (resource, lock_id, run_id, owner_id, acquired_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (lock.resource, lock.lock_id, lock.run_id, lock.owner_id, _iso(lock.acquired_at), _iso(lock.expires_at)),
                )
            except sqlite3.IntegrityError as exc:
                connection.rollback()
                raise RealRegistryConflict("run already owns a lock") from exc
            connection.commit()
        return lock

    def renew_lock(self, lock_id: str, owner_id: str, lease_seconds: int, now: datetime) -> LockLease:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        current = _utc(now)
        expires = current + timedelta(seconds=lease_seconds)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT resource, run_id, acquired_at, expires_at FROM real_run_locks WHERE lock_id=? AND owner_id=?",
                (lock_id, owner_id),
            ).fetchone()
            if row is None or _parse(row["expires_at"]) <= current:
                connection.rollback()
                raise RealRegistryConflict("lock is missing, expired, or owned by another operator")
            connection.execute("UPDATE real_run_locks SET expires_at=? WHERE lock_id=?", (_iso(expires), lock_id))
            connection.commit()
        return LockLease(row["resource"], lock_id, row["run_id"], owner_id, _parse(row["acquired_at"]), expires)

    def release_lock(self, lock_id: str, owner_id: str) -> None:
        with self._connect() as connection:
            deleted = connection.execute(
                "DELETE FROM real_run_locks WHERE lock_id=? AND owner_id=?", (lock_id, owner_id)
            ).rowcount
        if deleted != 1:
            raise RealRegistryConflict("lock is missing or owned by another operator")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("registry timestamps must include a timezone")
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)
