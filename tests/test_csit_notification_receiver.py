from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from src.csit.notification import (
    AllowlistedFixtureResolver,
    ExistingKmPipelineProcessor,
    NotificationError,
    NotificationEvent,
    NotificationReceiver,
    NotificationStore,
    ReceiverConfig,
)
from src.web_api.csit_notification_routes import router


def payload(event_id="evt-1", **changes):
    value = {
        "schema_version": "1.0-draft",
        "event_id": event_id,
        "event_type": "csit.test.document.available",
        "document_id": "doc-1",
        "document_version": "v1",
        "file_ref": {"fixture_id": "approved"},
        "occurred_at": "2026-09-21T01:00:00Z",
        "correlation_id": "corr-1",
    }
    value.update(changes)
    return value


def receiver(tmp_path, processor=None, **config_changes):
    config_values = {"database_path": tmp_path / "events.sqlite3", "enabled": True,
                     "auth_token": "test-secret", "eligibility_policy": "test-allow"}
    config_values.update(config_changes)
    config = ReceiverConfig(**config_values)
    return NotificationReceiver(config, store=NotificationStore(config.database_path), processor=processor)


def test_disabled_and_bad_auth_fail_closed(tmp_path):
    disabled = NotificationReceiver(ReceiverConfig(database_path=tmp_path / "off.sqlite3"))
    with pytest.raises(NotificationError) as exc:
        disabled.receive(payload(), "Bearer test-secret")
    assert exc.value.code == "receiver_disabled"
    with pytest.raises(NotificationError) as exc:
        receiver(tmp_path).receive(payload(), "Bearer wrong")
    assert exc.value.status_code == 401


def test_schema_and_unknown_event_are_rejected_before_persistence(tmp_path):
    target = receiver(tmp_path)
    with pytest.raises(NotificationError, match="required fields"):
        target.receive({"event_id": "x"}, "Bearer test-secret")
    with pytest.raises(NotificationError) as exc:
        target.receive(payload(event_type="csit.unknown"), "Bearer test-secret")
    assert exc.value.code == "unsupported_event"
    assert target.store.pending() == []


def test_accept_duplicate_and_reject_conflict(tmp_path):
    target = receiver(tmp_path)
    first = target.receive(payload(), "Bearer test-secret")
    second = target.receive(payload(), "Bearer test-secret")
    assert first["receipt_id"] == second["receipt_id"]
    assert second["duplicate"] is True
    with pytest.raises(NotificationError) as exc:
        target.receive(payload(document_version="v2"), "Bearer test-secret")
    assert exc.value.status_code == 409
    assert target.store.get("csit-proposed-source", "evt-1")["status"] == "received"


def test_concurrent_duplicate_creates_one_receipt(tmp_path):
    target = receiver(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: target.receive(payload(), "Bearer test-secret"), range(16)))
    assert len({item["receipt_id"] for item in results}) == 1
    assert len(target.store.pending()) == 1


def test_store_failure_never_returns_success(tmp_path):
    target = receiver(tmp_path)
    target.store.receive = lambda *_: (_ for _ in ()).throw(OSError("synthetic store failure"))
    with pytest.raises(NotificationError) as exc:
        target.receive(payload(), "Bearer test-secret")
    assert exc.value.status_code == 503


def test_recovery_and_pipeline_status(tmp_path):
    calls = []
    target = receiver(tmp_path, processor=lambda event, job_id: calls.append((event.event_id, job_id)))
    target.receive(payload(), "Bearer test-secret")
    assert target.dispatch_pending() == 1
    assert calls == [("evt-1", "km-csit-evt-1")]
    assert target.status("evt-1", "Bearer test-secret")["status"] == "completed"
    assert target.dispatch_pending() == 0


def test_policy_hold_does_not_publish_or_dispatch(tmp_path):
    target = receiver(tmp_path, eligibility_policy="test-hold", processor=lambda *_: pytest.fail("must not run"))
    target.receive(payload(), "Bearer test-secret")
    assert target.dispatch_pending() == 0
    status = target.status("evt-1", "Bearer test-secret")
    assert status["status"] == "held"
    assert status["error_code"] == "eligibility_policy_unconfigured"


def test_allowlisted_fixture_resolver_hash_and_path(tmp_path):
    fixture = tmp_path / "report.xlsx"
    fixture.write_bytes(b"synthetic-xlsx-fixture")
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    resolver = AllowlistedFixtureResolver({"approved": (fixture, digest)})
    event = NotificationEvent.parse(payload())
    resolved, actual = resolver.resolve(event)
    assert resolved == fixture.resolve() and actual == digest
    fixture.write_bytes(b"changed")
    with pytest.raises(NotificationError, match="checksum"):
        resolver.resolve(event)


def test_existing_pipeline_adapter_verifies_file_before_delegation(tmp_path):
    fixture = tmp_path / "report.xlsx"
    fixture.write_bytes(b"synthetic-xlsx-fixture")
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    calls = []
    adapter = ExistingKmPipelineProcessor(
        AllowlistedFixtureResolver({"approved": (fixture, digest)}),
        lambda **kwargs: calls.append(kwargs) or {"indexed": True},
    )
    target = receiver(tmp_path, processor=adapter)
    target.receive(payload(), "Bearer test-secret")
    target.dispatch_pending()
    assert calls[0]["document_id"] == "doc-1"
    assert calls[0]["metadata"]["sha256"] == digest
    assert target.status("evt-1", "Bearer test-secret")["status"] == "completed"


def test_http_receiver_contract_is_202_and_status_is_protected(tmp_path, monkeypatch):
    from fastapi import FastAPI
    import src.web_api.csit_notification_routes as routes
    target = receiver(tmp_path, processor=lambda *_: None)
    monkeypatch.setattr(routes, "_receiver", target)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/api/v1/integrations/csit/events", json=payload(), headers={"Authorization": "Bearer test-secret"})
        assert response.status_code == 202
        assert response.json()["processing_status"] == "received"
        assert client.get("/api/v1/integrations/csit/events/evt-1").status_code == 401
        assert client.get("/api/v1/integrations/csit/events/evt-1", headers={"Authorization": "Bearer test-secret"}).status_code == 200
