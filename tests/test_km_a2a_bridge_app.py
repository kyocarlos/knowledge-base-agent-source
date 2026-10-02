from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from km_a2a_bridge.app import create_app
from km_a2a_bridge.config import BridgeConfig
from km_a2a_bridge.journal import TaskJournal
from km_a2a_bridge.transport import MockA2ATransport

TOKEN = "bridge-control-secret"
TOKEN_HASH = hashlib.sha256(TOKEN.encode()).hexdigest()


def config(tmp_path, *, enabled=True):
    values = {
        "enabled": enabled,
        "allowed_profiles": {"anritsu": {"safe-profile"}},
        "journal_path": tmp_path / "tasks.sqlite3",
    }
    if enabled:
        values.update({
            "control_token_sha256": TOKEN_HASH,
            "agent_endpoints": {"anritsu": "https://anritsu.example"},
            "agent_credentials": {"anritsu": "different-outbound-secret"},
        })
    return BridgeConfig(**values)


def payload(**changes):
    values = {
        "job_type": "run_iperf_test",
        "environment": "anritsu",
        "profile_id": "safe-profile",
        "run_id": "run-api-1",
        "requested_by": "operator-1",
        "duration_seconds": 60,
        "test_cases": ["sa_dl_tcp"],
    }
    values.update(changes)
    return values


def test_health_is_safe_and_explicitly_mock_only(tmp_path):
    cfg = config(tmp_path, enabled=False)
    client = TestClient(create_app(cfg, TaskJournal(cfg.journal_path)))
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok", "enabled": False, "transport": "mock", "real_instrument_access": False
    }


def test_task_api_requires_control_token_and_never_returns_secrets(tmp_path):
    cfg = config(tmp_path)
    client = TestClient(create_app(cfg, TaskJournal(cfg.journal_path), MockA2ATransport()))
    assert client.post("/v1/tasks", json=payload()).status_code == 401
    assert client.post("/v1/tasks", headers={"Authorization": "Bearer wrong"}, json=payload()).status_code == 403
    response = client.post(
        "/v1/tasks", headers={"Authorization": f"Bearer {TOKEN}"}, json=payload()
    )
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "completed"
    assert body["status"] == {"test_status": "pending", "report_status": "pending", "ingest_status": "pending"}
    assert TOKEN not in response.text
    assert "different-outbound-secret" not in response.text


def test_task_lookup_and_idempotency_use_environment_and_run_id(tmp_path):
    cfg = config(tmp_path)
    transport = MockA2ATransport()
    client = TestClient(create_app(cfg, TaskJournal(cfg.journal_path), transport))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    first = client.post("/v1/tasks", headers=headers, json=payload())
    second = client.post("/v1/tasks", headers=headers, json=payload())
    lookup = client.get("/v1/tasks/anritsu/run-api-1", headers=headers)
    assert first.status_code == second.status_code == 202
    assert lookup.status_code == 200
    assert first.json() == second.json() == lookup.json()
    assert transport.calls == 1


def test_same_run_with_changed_payload_is_conflict(tmp_path):
    cfg = config(tmp_path)
    client = TestClient(create_app(cfg, TaskJournal(cfg.journal_path)))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/v1/tasks", headers=headers, json=payload()).status_code == 202
    conflict = client.post("/v1/tasks", headers=headers, json=payload(duration_seconds=120))
    assert conflict.status_code == 409


def test_disabled_bridge_rejects_dispatch_without_creating_task(tmp_path):
    cfg = config(tmp_path, enabled=False)
    # A disabled bridge intentionally has no usable control secret, so dispatch cannot authenticate.
    client = TestClient(create_app(cfg, TaskJournal(cfg.journal_path)))
    assert client.post("/v1/tasks", headers={"Authorization": f"Bearer {TOKEN}"}, json=payload()).status_code == 401
