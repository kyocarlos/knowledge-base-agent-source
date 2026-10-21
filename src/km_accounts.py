"""Per-instance KM user accounts and signed browser sessions.

The account database is deliberately the entry's report-registry database.
There is no central account table shared by Test, DA40, and RD2.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from .instance_isolation import InstanceIsolationError, VALID_INSTANCE_IDS


ACCOUNT_ROLES = frozenset({"admin", "user"})
SESSION_VERSION = 1


class AccountError(RuntimeError):
    pass


class InvalidCredentials(AccountError):
    pass


class SessionError(AccountError):
    pass


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise AccountError("password must contain at least 12 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt$16384$8$1${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = encoded.split("$", 5)
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=_unb64(salt), n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(actual, _unb64(expected))
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True)
class Account:
    username: str
    role: str
    active: bool


class AccountRegistry:
    """Small SQL registry with SQLite support for isolated tests and PostgreSQL runtime."""

    def __init__(self, database_url: str, instance_id: str):
        if instance_id not in VALID_INSTANCE_IDS:
            raise InstanceIsolationError("unknown KM instance")
        self.database_url = database_url
        self.instance_id = instance_id
        self.is_postgres = database_url.startswith(("postgresql://", "postgres://"))
        self._initialize()

    @classmethod
    def from_environment(cls) -> "AccountRegistry":
        url = os.getenv("KB_ACCOUNT_REGISTRY_URL") or os.getenv("KB_REPORT_REGISTRY_URL", "")
        instance_id = os.getenv("KM_INSTANCE_ID", "").strip().lower()
        if not url:
            raise InstanceIsolationError("missing KB_ACCOUNT_REGISTRY_URL")
        return cls(url, instance_id)

    @contextmanager
    def _connection(self) -> Iterator[object]:
        if self.is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - deployment dependency
                raise AccountError("PostgreSQL account registry requires psycopg") from exc
            with psycopg.connect(self.database_url, row_factory=dict_row) as connection:
                yield connection
            return
        path = self.database_url.removeprefix("sqlite:///")
        connection = sqlite3.connect(path)
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
                CREATE TABLE IF NOT EXISTS km_accounts (
                    instance_id TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL,
                    PRIMARY KEY (instance_id, username)
                )
            """))

    def create_or_reset(self, username: str, password: str, role: str = "user") -> Account:
        username = username.strip().lower()
        if not username or len(username) > 128:
            raise AccountError("invalid username")
        if role not in ACCOUNT_ROLES:
            raise AccountError("invalid role")
        now = int(time.time())
        password_hash = hash_password(password)
        with self._connection() as connection:
            existing = connection.execute(
                self._sql("SELECT username FROM km_accounts WHERE instance_id = ? AND username = ?"),
                (self.instance_id, username),
            ).fetchone()
            if existing:
                connection.execute(
                    self._sql("""
                        UPDATE km_accounts SET password_hash = ?, role = ?, active = TRUE, updated_at = ?
                        WHERE instance_id = ? AND username = ?
                    """),
                    (password_hash, role, now, self.instance_id, username),
                )
            else:
                connection.execute(
                    self._sql("""
                        INSERT INTO km_accounts (instance_id, username, password_hash, role, active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, TRUE, ?, ?)
                    """),
                    (self.instance_id, username, password_hash, role, now, now),
                )
        return Account(username=username, role=role, active=True)

    def set_active(self, username: str, active: bool) -> None:
        with self._connection() as connection:
            cursor = connection.execute(
                self._sql("UPDATE km_accounts SET active = ?, updated_at = ? WHERE instance_id = ? AND username = ?"),
                (active, int(time.time()), self.instance_id, username.strip().lower()),
            )
            if cursor.rowcount != 1:
                raise AccountError("account not found")

    def authenticate(self, username: str, password: str) -> Account:
        with self._connection() as connection:
            row = connection.execute(
                self._sql("""
                    SELECT username, password_hash, role, active FROM km_accounts
                    WHERE instance_id = ? AND username = ?
                """),
                (self.instance_id, username.strip().lower()),
            ).fetchone()
        if not row or not bool(row["active"]) or not verify_password(password, row["password_hash"]):
            raise InvalidCredentials("invalid username or password")
        return Account(username=row["username"], role=row["role"], active=bool(row["active"]))

    def list_accounts(self) -> list[Account]:
        with self._connection() as connection:
            rows = connection.execute(
                self._sql("SELECT username, role, active FROM km_accounts WHERE instance_id = ? ORDER BY username"),
                (self.instance_id,),
            ).fetchall()
        return [Account(username=row["username"], role=row["role"], active=bool(row["active"])) for row in rows]


def _session_key() -> bytes:
    value = os.getenv("KM_SESSION_SIGNING_KEY", "")
    if len(value) < 32:
        raise SessionError("KM_SESSION_SIGNING_KEY must be configured with at least 32 characters")
    return value.encode("utf-8")


def issue_session(account: Account, instance_id: str, ttl_seconds: int = 8 * 60 * 60) -> str:
    if instance_id not in VALID_INSTANCE_IDS:
        raise SessionError("unknown KM instance")
    payload = {
        "v": SESSION_VERSION,
        "instance_id": instance_id,
        "user_id": account.username,
        "role": account.role,
        "exp": int(time.time()) + ttl_seconds,
        "nonce": _b64(secrets.token_bytes(12)),
    }
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.new(_session_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def verify_session(token: str, expected_instance_id: str) -> dict[str, object]:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(_session_key(), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature)):
            raise SessionError("invalid signature")
        payload = json.loads(_unb64(body))
        if payload.get("v") != SESSION_VERSION:
            raise SessionError("unsupported session version")
        if payload.get("instance_id") != expected_instance_id:
            raise SessionError("cross-instance session rejected")
        if payload.get("role") not in ACCOUNT_ROLES or not payload.get("user_id"):
            raise SessionError("invalid session claims")
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise SessionError("session expired")
        return payload
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SessionError("invalid session") from exc
