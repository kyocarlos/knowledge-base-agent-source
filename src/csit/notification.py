"""Fail-closed KM receiver for the proposed CSIT notification contract.

This module deliberately owns transport receipt and dispatch durability only.
CSIT's event name, publication state, S2S authentication, and file delivery
are still proposed and are injected through small adapters.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


EVENT_TYPES = frozenset({"csit.test.document.available"})
SCHEMA_VERSION = "1.0-draft"


class NotificationError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 422):
        self.code, self.status_code = code, status_code
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


@dataclass(frozen=True)
class NotificationEvent:
    schema_version: str
    event_id: str
    event_type: str
    document_id: str
    document_version: str
    file_ref: Mapping[str, Any]
    occurred_at: str
    correlation_id: str

    @classmethod
    def parse(cls, value: Mapping[str, Any]) -> "NotificationEvent":
        if not isinstance(value, Mapping):
            raise NotificationError("invalid_payload", "payload must be an object")
        required = ("schema_version", "event_id", "event_type", "document_id",
                    "document_version", "file_ref", "occurred_at", "correlation_id")
        missing = [key for key in required if not str(value.get(key, "")).strip()]
        if missing:
            raise NotificationError("missing_field", "required fields are missing: " + ",".join(missing))
        if value["schema_version"] != SCHEMA_VERSION:
            raise NotificationError("unsupported_schema", "schema_version is not supported")
        if value["event_type"] not in EVENT_TYPES:
            raise NotificationError("unsupported_event", "event_type is not allowlisted")
        if not isinstance(value["file_ref"], Mapping):
            raise NotificationError("invalid_file_ref", "file_ref must be an object")
        return cls(*(str(value[k]).strip() if k != "file_ref" else dict(value[k]) for k in required))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version, "event_id": self.event_id,
            "event_type": self.event_type, "document_id": self.document_id,
            "document_version": self.document_version, "file_ref": dict(self.file_ref),
            "occurred_at": self.occurred_at, "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True)
class ReceiverConfig:
    enabled: bool = False
    auth_token: str = ""
    eligibility_policy: str = "disabled"
    database_path: Path = Path("data/csit-notification.sqlite3")

    @classmethod
    def from_env(cls) -> "ReceiverConfig":
        return cls(
            enabled=os.getenv("KM_CSIT_NOTIFICATION_ENABLED", "false").lower() == "true",
            auth_token=os.getenv("KM_CSIT_NOTIFICATION_AUTH_TOKEN", ""),
            eligibility_policy=os.getenv("KM_CSIT_NOTIFICATION_ELIGIBILITY", "disabled"),
            database_path=Path(os.getenv("KM_CSIT_NOTIFICATION_DB", "data/csit-notification.sqlite3")),
        )

    def usable(self) -> bool:
        return self.enabled and bool(self.auth_token) and self.eligibility_policy in {"test-allow", "test-hold"}


class NotificationAuthProvider(Protocol):
    def authenticate(self, authorization: str | None) -> str: ...


class StaticBearerAuth:
    """Test-only adapter; replace with formal S2S auth when jointly confirmed."""
    def __init__(self, token: str):
        self.token = token

    def authenticate(self, authorization: str | None) -> str:
        if not self.token or not authorization or not authorization.startswith("Bearer "):
            raise NotificationError("unauthorized", "notification authentication failed", 401)
        presented = authorization[7:].strip().encode()
        if not hmac.compare_digest(presented, self.token.encode()):
            raise NotificationError("unauthorized", "notification authentication failed", 401)
        return "csit-proposed-source"


class FixtureFileResolver(Protocol):
    def resolve(self, event: NotificationEvent) -> tuple[Path, str]: ...


class AllowlistedFixtureResolver:
    def __init__(self, fixtures: Mapping[str, tuple[str | Path, str]]):
        self.fixtures = {key: (Path(path).resolve(), digest.lower()) for key, (path, digest) in fixtures.items()}

    def resolve(self, event: NotificationEvent) -> tuple[Path, str]:
        fixture_id = str(event.file_ref.get("fixture_id", ""))
        try:
            path, expected = self.fixtures[fixture_id]
        except KeyError as exc:
            raise NotificationError("file_unavailable", "file reference is not allowlisted", 422) from exc
        if not path.is_file():
            raise NotificationError("file_unavailable", "allowlisted fixture is unavailable", 422)
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if not hmac.compare_digest(actual, expected):
            raise NotificationError("checksum_mismatch", "fixture checksum mismatch", 422)
        return path, actual


class ExistingKmPipelineProcessor:
    """Adapter that keeps file verification outside the existing KM pipeline.

    ``pipeline`` must be the already deployed KM validation/Knowledge Package
    entry point. The receiver never writes Qdrant/Neo4j directly and never
    creates a second approval path.
    """
    def __init__(self, resolver: FixtureFileResolver,
                 pipeline: Callable[..., Any]):
        self.resolver, self.pipeline = resolver, pipeline

    def __call__(self, event: NotificationEvent, job_id: str) -> Any:
        path, digest = self.resolver.resolve(event)
        metadata = {
            "source_system": "CSIT",
            "document_id": event.document_id,
            "document_version": event.document_version,
            "event_id": event.event_id,
            "job_id": job_id,
            "correlation_id": event.correlation_id,
            "sha256": digest,
        }
        return self.pipeline(input_path=path, document_id=event.document_id,
                             document_version=event.document_version,
                             metadata=metadata, event=event)


class NotificationStore:
    """SQLite event/dispatch store with an atomic insert-or-conflict decision."""
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with sqlite3.connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS csit_notification_events (
                source_identity TEXT NOT NULL, event_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
                receipt_id TEXT NOT NULL, status TEXT NOT NULL, job_id TEXT, stage TEXT NOT NULL,
                error_code TEXT NOT NULL DEFAULT '', payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(source_identity, event_id))""")

    def receive(self, source: str, event: NotificationEvent) -> tuple[dict[str, Any], bool]:
        digest = _digest(event.as_dict())
        now, receipt = _now(), secrets.token_urlsafe(18)
        with self._lock, sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM csit_notification_events WHERE source_identity=? AND event_id=?", (source, event.event_id)).fetchone()
            if row:
                existing = self._row(db, row)
                if existing["payload_hash"] != digest:
                    raise NotificationError("event_conflict", "event_id already has different content", 409)
                return existing, True
            db.execute("INSERT INTO csit_notification_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (source, event.event_id, digest, receipt, "received", None, "receipt", "", _canonical(event.as_dict()), now, now))
            return {"source_identity": source, "event_id": event.event_id, "payload_hash": digest, "receipt_id": receipt, "status": "received", "job_id": None, "stage": "receipt", "error_code": "", "created_at": now, "updated_at": now}, False

    @staticmethod
    def _row(db: sqlite3.Connection, row: tuple[Any, ...]) -> dict[str, Any]:
        cols = [item[1] for item in db.execute("PRAGMA table_info(csit_notification_events)").fetchall()]
        return dict(zip(cols, row))

    def get(self, source: str, event_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT * FROM csit_notification_events WHERE source_identity=? AND event_id=?", (source, event_id)).fetchone()
            return self._row(db, row) if row else None

    def update(self, source: str, event_id: str, **updates: Any) -> dict[str, Any]:
        allowed = {"status", "job_id", "stage", "error_code"}
        updates = {k: v for k, v in updates.items() if k in allowed}
        if not updates: return self.get(source, event_id) or {}
        updates["updated_at"] = _now()
        with self._lock, sqlite3.connect(self.path) as db:
            assignments = ",".join(f"{key}=?" for key in updates)
            db.execute(f"UPDATE csit_notification_events SET {assignments} WHERE source_identity=? AND event_id=?", (*updates.values(), source, event_id))
        return self.get(source, event_id) or {}

    def pending(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            rows = db.execute("SELECT * FROM csit_notification_events WHERE status='received' ORDER BY created_at").fetchall()
            return [self._row(db, row) for row in rows]


class NotificationReceiver:
    def __init__(self, config: ReceiverConfig, *, store: NotificationStore | None = None,
                 auth: NotificationAuthProvider | None = None,
                 processor: Callable[[NotificationEvent, str], str | None] | None = None):
        self.config, self.store = config, store or NotificationStore(config.database_path)
        self.auth, self.processor = auth or StaticBearerAuth(config.auth_token), processor

    def receive(self, payload: Mapping[str, Any], authorization: str | None) -> dict[str, Any]:
        if not self.config.usable():
            raise NotificationError("receiver_disabled", "CSIT notification receiver is disabled or not fully configured", 404)
        source = self.auth.authenticate(authorization)
        event = NotificationEvent.parse(payload)
        try:
            record, duplicate = self.store.receive(source, event)
        except NotificationError:
            raise
        except Exception as exc:
            # A 202 is only legal after the durable receipt commits.
            raise NotificationError("durable_store_unavailable", "event could not be durably saved", 503) from exc
        return {"event_id": event.event_id, "receipt_id": record["receipt_id"], "duplicate": duplicate,
                "processing_status": record["status"], "job_id": record.get("job_id"),
                "status_url": f"/api/v1/integrations/csit/events/{event.event_id}"}

    def dispatch_pending(self) -> int:
        if not self.config.usable(): return 0
        processed = 0
        for record in self.store.pending():
            source, event_id = record["source_identity"], record["event_id"]
            event = NotificationEvent.parse(json.loads(record["payload_json"]))
            if self.config.eligibility_policy != "test-allow":
                self.store.update(source, event_id, status="held", stage="eligibility", error_code="eligibility_policy_unconfigured")
                continue
            job_id = f"km-csit-{event_id}"
            self.store.update(source, event_id, status="processing", stage="pipeline", job_id=job_id)
            try:
                if self.processor is None:
                    raise NotificationError("pipeline_unconfigured", "existing KM pipeline adapter is not configured", 503)
                self.processor(event, job_id)
                self.store.update(source, event_id, status="completed", stage="pipeline")
            except NotificationError as exc:
                self.store.update(source, event_id, status="failed", stage="pipeline", error_code=exc.code)
            except Exception:
                self.store.update(source, event_id, status="failed", stage="pipeline", error_code="pipeline_failed")
            processed += 1
        return processed

    def status(self, event_id: str, authorization: str | None) -> dict[str, Any]:
        if not self.config.usable(): raise NotificationError("receiver_disabled", "receiver is disabled", 404)
        source = self.auth.authenticate(authorization)
        record = self.store.get(source, event_id)
        if not record: raise NotificationError("not_found", "event was not found", 404)
        return {key: record[key] for key in ("event_id", "receipt_id", "status", "job_id", "stage", "error_code", "created_at", "updated_at")}
