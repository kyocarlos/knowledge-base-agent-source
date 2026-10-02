"""Central KM account, grant, audit, and one-time entry-code control plane."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from .instance_isolation import VALID_INSTANCE_IDS
from .km_accounts import hash_password, verify_password


CONTROL_ISSUER = "km-control"
USER_STATUSES = frozenset({"pending", "active", "disabled"})
GRANT_ROLES = frozenset({"user", "admin"})


class ControlError(RuntimeError):
    pass


class ControlAuthenticationError(ControlError):
    pass


class ControlAuthorizationError(ControlError):
    pass


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _now() -> int:
    return int(time.time())


def _token_key(name: str) -> bytes:
    value = os.getenv(name, "")
    if len(value) < 32:
        raise ControlError(f"{name} must contain at least 32 characters")
    return value.encode("utf-8")


def _issue_token(claims: dict, key_name: str, ttl_seconds: int) -> str:
    payload = {**claims, "iss": CONTROL_ISSUER, "iat": _now(), "exp": _now() + ttl_seconds, "jti": _b64(secrets.token_bytes(18))}
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _b64(hmac.new(_token_key(key_name), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{signature}"


def _verify_token(token: str, key_name: str, audience: str) -> dict:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(_token_key(key_name), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature)):
            raise ControlAuthenticationError("invalid signature")
        payload = json.loads(_unb64(body))
        if payload.get("iss") != CONTROL_ISSUER or payload.get("aud") != audience:
            raise ControlAuthenticationError("invalid issuer or audience")
        if int(payload.get("exp", 0)) <= _now() or not payload.get("sub") or not payload.get("jti"):
            raise ControlAuthenticationError("expired or incomplete session")
        return payload
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControlAuthenticationError("invalid session") from exc


def issue_control_session(user: "ControlUser") -> str:
    return _issue_token({"sub": user.user_id, "aud": "km-control", "epoch": user.session_epoch, "admin": user.is_admin}, "KM_CONTROL_SESSION_SIGNING_KEY", 8 * 60 * 60)


def verify_control_session(token: str) -> dict:
    return _verify_token(token, "KM_CONTROL_SESSION_SIGNING_KEY", "km-control")


def issue_oidc_binding_session(identity_id: str) -> str:
    return _issue_token({"identity_id": identity_id, "aud": "km-oidc-binding"}, "KM_OIDC_BINDING_SIGNING_KEY", 10 * 60)


def verify_oidc_binding_session(token: str) -> dict:
    claims = _verify_token(token, "KM_OIDC_BINDING_SIGNING_KEY", "km-oidc-binding")
    if not claims.get("identity_id"):
        raise ControlAuthenticationError("invalid OIDC binding session")
    return claims


def issue_entry_session(user_id: str, instance_id: str, role: str, session_epoch: int) -> str:
    if instance_id not in VALID_INSTANCE_IDS or role not in GRANT_ROLES:
        raise ControlAuthorizationError("invalid instance grant")
    return _issue_token(
        {"sub": user_id, "aud": f"km-{instance_id}", "instance_id": instance_id, "role": role, "epoch": session_epoch},
        "KM_ENTRY_SESSION_SIGNING_KEY",
        15 * 60,
    )


def verify_entry_session(token: str, instance_id: str) -> dict:
    payload = _verify_token(token, "KM_ENTRY_SESSION_SIGNING_KEY", f"km-{instance_id}")
    if payload.get("instance_id") != instance_id or payload.get("role") not in GRANT_ROLES:
        raise ControlAuthenticationError("cross-instance session rejected")
    return payload


@dataclass(frozen=True)
class ControlUser:
    user_id: str
    username: str
    status: str
    is_admin: bool
    session_epoch: int


class ControlRegistry:
    """The only store for normal KM accounts and instance grants."""

    def __init__(self, database_url: str):
        if not database_url:
            raise ControlError("missing KM_CONTROL_DB_URL")
        self.database_url = database_url
        self.is_postgres = database_url.startswith(("postgresql://", "postgres://"))
        self._initialize()

    @classmethod
    def from_environment(cls) -> "ControlRegistry":
        return cls(os.getenv("KM_CONTROL_DB_URL", "").strip())

    @contextmanager
    def _connection(self) -> Iterator[object]:
        if self.is_postgres:
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover
                raise ControlError("Control DB requires psycopg") from exc
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
                CREATE TABLE IF NOT EXISTS km_users (
                    user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL, status TEXT NOT NULL,
                    is_admin BOOLEAN NOT NULL DEFAULT FALSE, session_epoch BIGINT NOT NULL DEFAULT 1,
                    created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
                )
            """))
            connection.execute(self._sql("""
                CREATE TABLE IF NOT EXISTS km_instance_grants (
                    user_id TEXT NOT NULL, instance_id TEXT NOT NULL, role TEXT NOT NULL,
                    active BOOLEAN NOT NULL DEFAULT TRUE, approved_by TEXT NOT NULL,
                    approved_at BIGINT NOT NULL, updated_at BIGINT NOT NULL,
                    PRIMARY KEY (user_id, instance_id)
                )
            """))
            connection.execute(self._sql("""
                CREATE TABLE IF NOT EXISTS km_login_codes (
                    code_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, instance_id TEXT NOT NULL,
                    expires_at BIGINT NOT NULL, used_at BIGINT
                )
            """))
            connection.execute(self._sql("""
                CREATE TABLE IF NOT EXISTS km_audit_events (
                    event_id TEXT PRIMARY KEY, occurred_at BIGINT NOT NULL, actor_user_id TEXT,
                    target_user_id TEXT, event_type TEXT NOT NULL, detail_json TEXT NOT NULL
                )
            """))
            connection.execute(self._sql("""
                CREATE TABLE IF NOT EXISTS km_oidc_transactions (
                    state_hash TEXT PRIMARY KEY, nonce TEXT NOT NULL, verifier TEXT NOT NULL,
                    expires_at BIGINT NOT NULL, used_at BIGINT
                )
            """))
            connection.execute(self._sql("""
                CREATE TABLE IF NOT EXISTS km_external_identities (
                    identity_id TEXT PRIMARY KEY, provider_issuer TEXT NOT NULL, subject TEXT NOT NULL,
                    user_id TEXT, binding_status TEXT NOT NULL, profile_json TEXT NOT NULL,
                    requested_at BIGINT NOT NULL, verified_at BIGINT, approved_at BIGINT,
                    approved_by TEXT, updated_at BIGINT NOT NULL,
                    UNIQUE(provider_issuer, subject)
                )
            """))

    def _audit(self, connection: object, event_type: str, actor_user_id: str | None, target_user_id: str | None, detail: dict | None = None) -> None:
        connection.execute(self._sql("INSERT INTO km_audit_events (event_id, occurred_at, actor_user_id, target_user_id, event_type, detail_json) VALUES (?, ?, ?, ?, ?, ?)"),
            (str(uuid.uuid4()), _now(), actor_user_id, target_user_id, event_type, json.dumps(detail or {}, separators=(",", ":"), sort_keys=True)))

    @staticmethod
    def _user(row: object | None) -> ControlUser | None:
        if not row:
            return None
        return ControlUser(user_id=row["user_id"], username=row["username"], status=row["status"], is_admin=bool(row["is_admin"]), session_epoch=int(row["session_epoch"]))

    def register(self, username: str, password: str) -> ControlUser:
        username = username.strip().lower()
        if not username or len(username) > 128:
            raise ControlError("invalid username")
        now, user_id = _now(), str(uuid.uuid4())
        try:
            with self._connection() as connection:
                connection.execute(self._sql("INSERT INTO km_users (user_id, username, password_hash, status, is_admin, session_epoch, created_at, updated_at) VALUES (?, ?, ?, 'pending', FALSE, 1, ?, ?)"),
                    (user_id, username, hash_password(password), now, now))
                self._audit(connection, "user_registered", user_id, user_id)
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise ControlError("username already exists") from None
            raise
        return ControlUser(user_id=user_id, username=username, status="pending", is_admin=False, session_epoch=1)

    def create_active_with_grant(self, actor_user_id: str, username: str, password: str, role: str, instance_id: str) -> ControlUser:
        """Create an active account and exactly one initial grant atomically."""
        username = username.strip().lower()
        if not username or len(username) > 128:
            raise ControlError("invalid username")
        if role not in GRANT_ROLES or instance_id not in VALID_INSTANCE_IDS:
            raise ControlError("invalid initial grant")
        now, user_id = _now(), str(uuid.uuid4())
        try:
            with self._connection() as connection:
                connection.execute(self._sql("INSERT INTO km_users (user_id, username, password_hash, status, is_admin, session_epoch, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, 1, ?, ?)"),
                    (user_id, username, hash_password(password), role == "admin", now, now))
                connection.execute(self._sql("INSERT INTO km_instance_grants (user_id, instance_id, role, active, approved_by, approved_at, updated_at) VALUES (?, ?, ?, TRUE, ?, ?, ?)"),
                    (user_id, instance_id, role, actor_user_id, now, now))
                self._audit(connection, "admin_user_created", actor_user_id, user_id, {"instance_id": instance_id, "role": role})
        except Exception as exc:
            if "unique" in str(exc).lower():
                raise ControlError("username already exists") from None
            raise
        return ControlUser(user_id=user_id, username=username, status="active", is_admin=role == "admin", session_epoch=1)

    def bootstrap_admin(self, username: str, password: str) -> ControlUser:
        """Create the one initial Control admin; refuse after any admin exists."""
        username = username.strip().lower()
        if not username:
            raise ControlError("invalid username")
        now, user_id = _now(), str(uuid.uuid4())
        with self._connection() as connection:
            if connection.execute(self._sql("SELECT user_id FROM km_users WHERE is_admin = TRUE LIMIT 1")).fetchone():
                raise ControlError("a Control admin already exists")
            connection.execute(self._sql("INSERT INTO km_users (user_id, username, password_hash, status, is_admin, session_epoch, created_at, updated_at) VALUES (?, ?, ?, 'active', TRUE, 1, ?, ?)"),
                (user_id, username, hash_password(password), now, now))
            self._audit(connection, "bootstrap_admin_created", user_id, user_id)
        return ControlUser(user_id=user_id, username=username, status="active", is_admin=True, session_epoch=1)

    def get_user(self, user_id: str) -> ControlUser | None:
        with self._connection() as connection:
            return self._user(connection.execute(self._sql("SELECT user_id, username, status, is_admin, session_epoch FROM km_users WHERE user_id = ?"), (user_id,)).fetchone())

    def list_users(self) -> list[ControlUser]:
        with self._connection() as connection:
            rows = connection.execute(self._sql("SELECT user_id, username, status, is_admin, session_epoch FROM km_users ORDER BY username")).fetchall()
        return [self._user(row) for row in rows if self._user(row)]

    def authenticate(self, username: str, password: str) -> ControlUser:
        with self._connection() as connection:
            row = connection.execute(self._sql("SELECT * FROM km_users WHERE username = ?"), (username.strip().lower(),)).fetchone()
            user = self._user(row)
            if not row or not user or not verify_password(password, row["password_hash"]):
                raise ControlAuthenticationError("invalid username or password")
            self._audit(connection, "login_succeeded" if user.status == "active" else "login_pending_or_disabled", user.user_id, user.user_id)
        if user.status != "active":
            raise ControlAuthorizationError("account is not active")
        return user

    def set_user_status(self, actor_user_id: str, user_id: str, status: str) -> ControlUser:
        if status not in USER_STATUSES:
            raise ControlError("invalid account status")
        with self._connection() as connection:
            cursor = connection.execute(self._sql("UPDATE km_users SET status = ?, session_epoch = session_epoch + 1, updated_at = ? WHERE user_id = ?"), (status, _now(), user_id))
            if cursor.rowcount != 1:
                raise ControlError("user not found")
            self._audit(connection, "user_status_changed", actor_user_id, user_id, {"status": status})
        user = self.get_user(user_id)
        assert user is not None
        return user

    def delete_user(self, actor_user_id: str, user_id: str) -> ControlUser:
        """Soft-delete an account, revoke grants, and invalidate all sessions."""
        if actor_user_id == user_id:
            raise ControlError("cannot delete the current admin account")
        now = _now()
        with self._connection() as connection:
            row = connection.execute(
                self._sql("SELECT user_id, username, status, is_admin, session_epoch FROM km_users WHERE user_id = ?"),
                (user_id,),
            ).fetchone()
            if not self._user(row):
                raise ControlError("user not found")
            connection.execute(
                self._sql("UPDATE km_users SET status = 'disabled', session_epoch = session_epoch + 1, updated_at = ? WHERE user_id = ?"),
                (now, user_id),
            )
            connection.execute(
                self._sql("UPDATE km_instance_grants SET active = FALSE, updated_at = ? WHERE user_id = ? AND active = TRUE"),
                (now, user_id),
            )
            self._audit(connection, "user_deleted", actor_user_id, user_id)
        user = self.get_user(user_id)
        assert user is not None
        return user

    def permanently_delete_user(self, actor_user_id: str, user_id: str) -> None:
        """Permanently remove a disabled account while retaining audit history."""
        if actor_user_id == user_id:
            raise ControlError("cannot delete the current admin account")
        with self._connection() as connection:
            row = connection.execute(
                self._sql("SELECT user_id, username, status, is_admin, session_epoch FROM km_users WHERE user_id = ?"),
                (user_id,),
            ).fetchone()
            user = self._user(row)
            if not user:
                raise ControlError("user not found")
            if user.status != "disabled":
                raise ControlError("only disabled accounts can be permanently deleted")
            active_grant = connection.execute(
                self._sql("SELECT 1 FROM km_instance_grants WHERE user_id = ? AND active = TRUE LIMIT 1"),
                (user_id,),
            ).fetchone()
            if active_grant:
                raise ControlError("account has active grants")
            connection.execute(self._sql("DELETE FROM km_instance_grants WHERE user_id = ?"), (user_id,))
            connection.execute(self._sql("DELETE FROM km_login_codes WHERE user_id = ?"), (user_id,))
            connection.execute(self._sql("DELETE FROM km_external_identities WHERE user_id = ?"), (user_id,))
            connection.execute(self._sql("DELETE FROM km_users WHERE user_id = ?"), (user_id,))
            self._audit(connection, "user_permanently_deleted", actor_user_id, user_id)

    def grant(self, actor_user_id: str, user_id: str, instance_id: str, role: str) -> None:
        if instance_id not in VALID_INSTANCE_IDS or role not in GRANT_ROLES:
            raise ControlError("invalid grant")
        now = _now()
        with self._connection() as connection:
            if not self._user(connection.execute(self._sql("SELECT user_id, username, status, is_admin, session_epoch FROM km_users WHERE user_id = ?"), (user_id,)).fetchone()):
                raise ControlError("user not found")
            existing = connection.execute(self._sql("SELECT user_id FROM km_instance_grants WHERE user_id = ? AND instance_id = ?"), (user_id, instance_id)).fetchone()
            if existing:
                connection.execute(self._sql("UPDATE km_instance_grants SET role = ?, active = TRUE, approved_by = ?, approved_at = ?, updated_at = ? WHERE user_id = ? AND instance_id = ?"), (role, actor_user_id, now, now, user_id, instance_id))
            else:
                connection.execute(self._sql("INSERT INTO km_instance_grants (user_id, instance_id, role, active, approved_by, approved_at, updated_at) VALUES (?, ?, ?, TRUE, ?, ?, ?)"), (user_id, instance_id, role, actor_user_id, now, now))
            connection.execute(self._sql("UPDATE km_users SET session_epoch = session_epoch + 1, updated_at = ? WHERE user_id = ?"), (now, user_id))
            self._audit(connection, "grant_changed", actor_user_id, user_id, {"instance_id": instance_id, "role": role})

    def grants_for(self, user_id: str) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(self._sql("SELECT instance_id, role FROM km_instance_grants WHERE user_id = ? AND active = TRUE ORDER BY instance_id"), (user_id,)).fetchall()
        return [{"instance_id": row["instance_id"], "role": row["role"]} for row in rows]

    def revoke_grant(self, actor_user_id: str, user_id: str, instance_id: str) -> None:
        if instance_id not in VALID_INSTANCE_IDS:
            raise ControlError("invalid instance")
        now = _now()
        with self._connection() as connection:
            cursor = connection.execute(
                self._sql("UPDATE km_instance_grants SET active = FALSE, updated_at = ? WHERE user_id = ? AND instance_id = ? AND active = TRUE"),
                (now, user_id, instance_id),
            )
            if cursor.rowcount != 1:
                raise ControlError("active grant not found")
            connection.execute(
                self._sql("UPDATE km_users SET session_epoch = session_epoch + 1, updated_at = ? WHERE user_id = ?"),
                (now, user_id),
            )
            self._audit(connection, "grant_revoked", actor_user_id, user_id, {"instance_id": instance_id})

    def create_login_code(self, user: ControlUser, instance_id: str) -> str:
        grants = {grant["instance_id"]: grant["role"] for grant in self.grants_for(user.user_id)}
        if user.status != "active" or instance_id not in grants:
            raise ControlAuthorizationError("instance is not granted")
        raw_code, now = _b64(secrets.token_bytes(32)), _now()
        with self._connection() as connection:
            connection.execute(self._sql("INSERT INTO km_login_codes (code_hash, user_id, instance_id, expires_at, used_at) VALUES (?, ?, ?, ?, NULL)"), (hashlib.sha256(raw_code.encode()).hexdigest(), user.user_id, instance_id, now + 60))
            self._audit(connection, "instance_selected", user.user_id, user.user_id, {"instance_id": instance_id})
        return raw_code

    def consume_login_code(self, code: str, expected_instance_id: str) -> tuple[ControlUser, str]:
        digest, now = hashlib.sha256(code.encode()).hexdigest(), _now()
        with self._connection() as connection:
            row = connection.execute(self._sql("SELECT user_id, instance_id, expires_at, used_at FROM km_login_codes WHERE code_hash = ?"), (digest,)).fetchone()
            if not row or row["instance_id"] != expected_instance_id or row["used_at"] is not None or int(row["expires_at"]) <= now:
                raise ControlAuthenticationError("invalid or expired entry code")
            cursor = connection.execute(self._sql("UPDATE km_login_codes SET used_at = ? WHERE code_hash = ? AND used_at IS NULL"), (now, digest))
            if cursor.rowcount != 1:
                raise ControlAuthenticationError("entry code already used")
            user = self._user(connection.execute(self._sql("SELECT user_id, username, status, is_admin, session_epoch FROM km_users WHERE user_id = ?"), (row["user_id"],)).fetchone())
            if not user or user.status != "active":
                raise ControlAuthorizationError("account is not active")
            grant = connection.execute(self._sql("SELECT role FROM km_instance_grants WHERE user_id = ? AND instance_id = ? AND active = TRUE"), (user.user_id, expected_instance_id)).fetchone()
            if not grant:
                raise ControlAuthorizationError("instance is not granted")
            self._audit(connection, "entry_code_consumed", user.user_id, user.user_id, {"instance_id": expected_instance_id})
        return user, grant["role"]

    def validate_entry_claims(self, user_id: str, instance_id: str, role: str, epoch: int) -> None:
        user = self.get_user(user_id)
        if not user or user.status != "active" or user.session_epoch != int(epoch):
            raise ControlAuthorizationError("session revoked")
        grants = {grant["instance_id"]: grant["role"] for grant in self.grants_for(user_id)}
        if grants.get(instance_id) != role:
            raise ControlAuthorizationError("grant revoked or changed")

    def create_oidc_transaction(self) -> tuple[str, str, str]:
        state, verifier, nonce, now = _b64(secrets.token_bytes(32)), _b64(secrets.token_bytes(48)), _b64(secrets.token_bytes(24)), _now()
        with self._connection() as connection:
            connection.execute(self._sql("INSERT INTO km_oidc_transactions (state_hash, nonce, verifier, expires_at, used_at) VALUES (?, ?, ?, ?, NULL)"), (hashlib.sha256(state.encode()).hexdigest(), nonce, verifier, now + 300))
        return state, verifier, nonce

    def consume_oidc_transaction(self, state: str) -> tuple[str, str]:
        digest, now = hashlib.sha256(state.encode()).hexdigest(), _now()
        with self._connection() as connection:
            row = connection.execute(self._sql("SELECT nonce, verifier, expires_at, used_at FROM km_oidc_transactions WHERE state_hash = ?"), (digest,)).fetchone()
            if not row or row["used_at"] is not None or int(row["expires_at"]) <= now:
                raise ControlAuthenticationError("OIDC state is invalid or expired")
            cursor = connection.execute(self._sql("UPDATE km_oidc_transactions SET used_at = ? WHERE state_hash = ? AND used_at IS NULL"), (now, digest))
            if cursor.rowcount != 1:
                raise ControlAuthenticationError("OIDC state already used")
        return str(row["nonce"]), str(row["verifier"])

    def upsert_external_identity(self, provider_issuer: str, subject: str, profile: dict) -> dict:
        if not provider_issuer or not subject:
            raise ControlError("OIDC issuer and subject are required")
        now = _now()
        with self._connection() as connection:
            row = connection.execute(self._sql("SELECT * FROM km_external_identities WHERE provider_issuer = ? AND subject = ?"), (provider_issuer, subject)).fetchone()
            if row:
                connection.execute(self._sql("UPDATE km_external_identities SET profile_json = ?, updated_at = ? WHERE identity_id = ?"), (json.dumps(profile, separators=(",", ":"), sort_keys=True), now, row["identity_id"]))
                row = connection.execute(self._sql("SELECT * FROM km_external_identities WHERE identity_id = ?"), (row["identity_id"],)).fetchone()
            else:
                identity_id = str(uuid.uuid4())
                connection.execute(self._sql("INSERT INTO km_external_identities (identity_id, provider_issuer, subject, user_id, binding_status, profile_json, requested_at, verified_at, approved_at, approved_by, updated_at) VALUES (?, ?, ?, NULL, 'pending', ?, ?, NULL, NULL, NULL, ?)"), (identity_id, provider_issuer, subject, json.dumps(profile, separators=(",", ":"), sort_keys=True), now, now))
                self._audit(connection, "oidc_identity_pending", None, None, {"identity_id": identity_id, "issuer": provider_issuer})
                row = connection.execute(self._sql("SELECT * FROM km_external_identities WHERE identity_id = ?"), (identity_id,)).fetchone()
        return dict(row)

    def get_external_identity(self, identity_id: str) -> dict | None:
        with self._connection() as connection:
            row = connection.execute(self._sql("SELECT * FROM km_external_identities WHERE identity_id = ?"), (identity_id,)).fetchone()
        return dict(row) if row else None

    def verify_external_identity_local_account(self, identity_id: str, user: ControlUser) -> None:
        now = _now()
        with self._connection() as connection:
            row = connection.execute(self._sql("SELECT binding_status FROM km_external_identities WHERE identity_id = ?"), (identity_id,)).fetchone()
            if not row or row["binding_status"] != "pending":
                raise ControlError("OIDC identity is not pending")
            connection.execute(self._sql("UPDATE km_external_identities SET user_id = ?, binding_status = 'awaiting_approval', verified_at = ?, updated_at = ? WHERE identity_id = ?"), (user.user_id, now, now, identity_id))
            self._audit(connection, "oidc_local_account_verified", user.user_id, user.user_id, {"identity_id": identity_id})

    def approve_external_identity(self, actor_user_id: str, identity_id: str) -> ControlUser:
        now = _now()
        with self._connection() as connection:
            row = connection.execute(self._sql("SELECT user_id, binding_status FROM km_external_identities WHERE identity_id = ?"), (identity_id,)).fetchone()
            if not row or row["binding_status"] != "awaiting_approval" or not row["user_id"]:
                raise ControlError("OIDC identity is not ready for approval")
            user = self._user(connection.execute(self._sql("SELECT user_id, username, status, is_admin, session_epoch FROM km_users WHERE user_id = ?"), (row["user_id"],)).fetchone())
            if not user:
                raise ControlError("bound local account no longer exists")
            connection.execute(self._sql("UPDATE km_external_identities SET binding_status = 'bound', approved_at = ?, approved_by = ?, updated_at = ? WHERE identity_id = ?"), (now, actor_user_id, now, identity_id))
            connection.execute(self._sql("UPDATE km_users SET session_epoch = session_epoch + 1, updated_at = ? WHERE user_id = ?"), (now, user.user_id))
            self._audit(connection, "oidc_identity_bound", actor_user_id, user.user_id, {"identity_id": identity_id})
        approved = self.get_user(user.user_id)
        assert approved is not None
        return approved

    def list_external_identities(self, only_pending: bool = False) -> list[dict]:
        statement = "SELECT * FROM km_external_identities"
        if only_pending:
            statement += " WHERE binding_status IN ('pending', 'awaiting_approval')"
        statement += " ORDER BY requested_at DESC"
        with self._connection() as connection:
            return [dict(row) for row in connection.execute(self._sql(statement)).fetchall()]
