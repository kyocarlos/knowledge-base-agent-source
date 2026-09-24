from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

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


def build_report(path: Path, run_id: str = "KM-CSIT-SIM-001") -> None:
    workbook = Workbook()
    manifest = workbook.active
    manifest.title = "Manifest"
    manifest.append(["key", "value"])
    for key, value in {
        "schema_version": "1.0", "run_id": run_id, "environment": "anritsu",
        "project_code": "SCU2060", "dut_model": "DUT-A",
        "started_at": "2026-09-23T08:00:00+08:00", "finished_at": "2026-09-23T08:10:00+08:00",
        "overall_verdict": "Pass",
    }.items():
        manifest.append([key, value])
    for name, headers, rows in (
        ("RadioConfig", ["key", "value", "unit"], [["band", "n78", ""]]),
        ("TestCases", ["case_id", "name", "status"], [["TC-01", "CSIT notification throughput", "completed"]]),
        ("Measurements", ["case_id", "metric", "value", "unit", "lower_limit", "upper_limit"], [["TC-01", "throughput", 950.5, "Mbps", 900, None]]),
        ("Verdicts", ["case_id", "verdict", "reason"], [["TC-01", "Pass", "validated"]]),
        ("RawArtifacts", ["artifact_path", "sha256"], []),
    ):
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    workbook.save(path)


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
    target = receiver(tmp_path, processor=lambda event, job_id: calls.append((event.event_id, job_id)) or {
        "success": True, "stage": "pipeline", "required_stores": ["qdrant", "neo4j"],
        "completed_stores": ["qdrant", "neo4j"],
    })
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
        lambda **kwargs: calls.append(kwargs) or {
            "success": True, "stage": "pipeline", "required_stores": ["qdrant", "neo4j"],
            "completed_stores": ["qdrant", "neo4j"],
        },
    )
    target = receiver(tmp_path, processor=adapter)
    target.receive(payload(), "Bearer test-secret")
    target.dispatch_pending()
    assert calls[0]["document_id"] == "doc-1"
    assert calls[0]["metadata"]["sha256"] == digest
    assert target.status("evt-1", "Bearer test-secret")["status"] == "completed"


def test_authoritative_pipeline_uses_submission_and_existing_ingest_queue(tmp_path, monkeypatch):
    from src.csit.notification_pipeline import CsitAuthoritativePipeline
    import src.web_api.tasks as tasks

    fixture = tmp_path / "csit-approved.xlsx"
    build_report(fixture)
    digest = hashlib.sha256(fixture.read_bytes()).hexdigest()
    queued = Mock(id="celery-csit-1")
    staged_upload = tmp_path / "uploads"
    monkeypatch.setenv("KB_REPORT_REGISTRY_URL", f"sqlite:///{tmp_path}/registry.sqlite3")
    monkeypatch.setenv("KB_REPORT_STAGING_ROOT", str(tmp_path / "staging"))
    monkeypatch.setenv("KM_CSIT_NOTIFICATION_DB", str(tmp_path / "receipts.sqlite3"))
    monkeypatch.setattr(tasks, "INGEST_UPLOAD_ROOT", staged_upload)
    recorded = []
    monkeypatch.setattr(tasks, "set_ingest_task_state", lambda task_id, state, **_kwargs: recorded.append((task_id, state)) or state)
    monkeypatch.setattr(tasks, "create_ingest_task_id", lambda: "ingest-csit-1")
    pipeline = CsitAuthoritativePipeline(
        AllowlistedFixtureResolver({"approved": (fixture, digest)}),
        enqueue=lambda **kwargs: queued,
    )
    result = pipeline(NotificationEvent.parse(payload()), "km-csit-evt-1")
    assert result["success"] is True and result["terminal"] is False
    assert result["job_id"] == "celery-csit-1"
    assert recorded[0][1]["source_system"] == "CSIT"
    assert recorded[0][1]["publish_status"] == "published"
    assert recorded[0][1]["document_id"] == "doc-1"


def test_queued_receipt_becomes_terminal_only_after_worker_result(tmp_path):
    target = receiver(tmp_path, processor=lambda *_: {
        "success": True, "terminal": False, "job_id": "celery-1", "stage": "queued",
    })
    target.receive(payload(), "Bearer test-secret")
    assert target.dispatch_pending() == 1
    assert target.status("evt-1", "Bearer test-secret")["status"] == "queued"
    target.store.complete_queued("csit-proposed-source", "evt-1", status="completed", stage="ingest_completed")
    assert target.status("evt-1", "Bearer test-secret")["status"] == "completed"


def test_existing_worker_terminal_state_updates_queued_receipt(tmp_path, monkeypatch):
    from src.web_api.tasks import ingest_csit_notification_task, ingest_file_task

    target = receiver(tmp_path, processor=lambda *_: {
        "success": True, "terminal": False, "job_id": "celery-1", "stage": "queued",
    })
    target.receive(payload(), "Bearer test-secret")
    target.dispatch_pending()
    monkeypatch.setattr(ingest_file_task, "run", lambda _task_id: {"status": "completed", "task_id": "ingest-1"})
    result = ingest_csit_notification_task.run("ingest-1", str(target.store.path), "csit-proposed-source", "evt-1")
    assert result["status"] == "completed"
    assert target.status("evt-1", "Bearer test-secret")["status"] == "completed"


def test_http_receiver_contract_is_202_and_status_is_protected(tmp_path, monkeypatch):
    from fastapi import FastAPI
    import src.web_api.csit_notification_routes as routes
    target = receiver(tmp_path, processor=lambda *_: {
        "success": True, "stage": "pipeline", "required_stores": [], "completed_stores": [],
    })
    monkeypatch.setattr(routes, "_receiver", target)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/api/v1/integrations/csit/events", json=payload(), headers={"Authorization": "Bearer test-secret"})
        assert response.status_code == 202
        assert response.json()["processing_status"] == "received"
        assert client.get("/api/v1/integrations/csit/events/evt-1").status_code == 401
        assert client.get("/api/v1/integrations/csit/events/evt-1", headers={"Authorization": "Bearer test-secret"}).status_code == 200


def test_processor_false_or_partial_never_completes(tmp_path):
    for result, expected in [
        ({"success": False, "stage": "qdrant", "error_code": "write_failed"}, "failed"),
        ({"success": True, "stage": "pipeline", "required_stores": ["qdrant", "neo4j"], "completed_stores": ["qdrant"]}, "partial_failed"),
    ]:
        target = receiver(tmp_path / expected, processor=lambda *_args, result=result: result)
        target.receive(payload(event_id=expected), "Bearer test-secret")
        assert target.dispatch_pending() == 1
        status = target.status(expected, "Bearer test-secret")
        assert status["status"] == expected


def test_atomic_claim_and_stale_processing_recovery(tmp_path):
    target = receiver(tmp_path, processor=lambda *_: {
        "success": True, "stage": "pipeline", "required_stores": [], "completed_stores": [],
    })
    target.receive(payload(), "Bearer test-secret")
    first = target.store.claim_pending(lease_seconds=1)
    assert len(first) == 1
    assert target.store.claim_pending(lease_seconds=1) == []
    with target.store._lock, __import__("sqlite3").connect(target.store.path) as db:
        db.execute("UPDATE csit_notification_events SET lease_until='2000-01-01T00:00:00+00:00' WHERE event_id='evt-1'")
    recovered = target.store.claim_pending(lease_seconds=1)
    assert len(recovered) == 1 and recovered[0]["attempt_count"] == 2


def test_concurrent_dispatch_has_one_processor_call(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    calls = []
    target = receiver(tmp_path, processor=lambda *_: calls.append(1) or {
        "success": True, "stage": "pipeline", "required_stores": [], "completed_stores": [],
    })
    target.receive(payload(), "Bearer test-secret")
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: target.dispatch_pending(), range(2)))
    assert calls == [1]
