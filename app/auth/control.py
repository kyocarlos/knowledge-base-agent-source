"""Control DB identity bindings and grants; legacy grants remain additive."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable


class ControlStore:
    def __init__(self, path: str) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS identity_bindings (
              issuer TEXT NOT NULL, subject TEXT NOT NULL, user_id TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('pending','approved','revoked')),
              approved_by TEXT, approved_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              PRIMARY KEY (issuer, subject));
            CREATE TABLE IF NOT EXISTS grants (
              user_id TEXT NOT NULL, permission TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'control',
              PRIMARY KEY (user_id, permission));
            """)

    def _connect(self):
        return sqlite3.connect(self.path)

    def binding_status(self, issuer: str, subject: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT status FROM identity_bindings WHERE issuer=? AND subject=?", (issuer, subject)).fetchone()
        return row[0] if row else None

    def create_pending_binding(self, issuer: str, subject: str, user_id: str) -> None:
        with self._connect() as db:
            db.execute("INSERT OR IGNORE INTO identity_bindings(issuer,subject,user_id,status) VALUES (?,?,?,'pending')", (issuer, subject, user_id))

    def approve_binding(self, issuer: str, subject: str, approver: str) -> None:
        with self._connect() as db:
            updated = db.execute("UPDATE identity_bindings SET status='approved', approved_by=?, approved_at=CURRENT_TIMESTAMP WHERE issuer=? AND subject=? AND status='pending'", (approver, issuer, subject)).rowcount
        if updated != 1:
            raise ValueError("binding is not pending")

    def control_grants(self, user_id: str) -> set[str]:
        with self._connect() as db:
            rows = db.execute("SELECT permission FROM grants WHERE user_id=?", (user_id,)).fetchall()
        return {row[0] for row in rows}


def effective_grants(control: ControlStore, user_id: str, local_grants: Iterable[str]) -> set[str]:
    """Existing local-account grants are retained; Control DB supplies controlled additions."""
    return set(local_grants) | control.control_grants(user_id)
