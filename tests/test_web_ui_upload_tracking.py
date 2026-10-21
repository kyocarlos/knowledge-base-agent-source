"""/api/ui/upload/ingest: session-bound UI upload is tracked as queued / queue_failed."""
from __future__ import annotations

import pytest


@pytest.fixture()
def client(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import src.web_api as web
    from src.web_api import tasks
    import src.ingest_registry as ingest_registry
    import src.ui_upload_tracking as tracking

    calls = {"record": [], "status": [], "registry": [], "queue_error": None, "identity": {"instance_id": "test"}}

    class FakeRegistry:
        def record_event(self, *args, **kwargs):
            calls["registry"].append(args[0])

        def register(self, identity, task_id):
            return {"task_id": task_id}, False

        def update_status(self, task_id, status):
            calls["registry"].append(status)

    class FakeAsyncResult:
        id = "celery-1"

    def fake_apply_async(*args, **kwargs):
        if calls["queue_error"] is not None:
            raise calls["queue_error"]
        return FakeAsyncResult()

    monkeypatch.setattr(web, "configured_instance_id", lambda: "test")
    monkeypatch.setattr(tasks, "INGEST_UPLOAD_ROOT", tmp_path)
    monkeypatch.setattr(tasks, "set_ingest_task_state", lambda task_id, state: None)
    monkeypatch.setattr(tasks, "get_ingest_task_state", lambda task_id: None)
    monkeypatch.setattr(tasks, "get_ingest_task_state_by_file_hash", lambda file_hash: None)
    monkeypatch.setattr(tasks, "get_ingest_queue_position", lambda task_id: 1)
    monkeypatch.setattr(tasks.ingest_file_task, "apply_async", fake_apply_async)
    monkeypatch.setattr(ingest_registry, "IngestRegistry", FakeRegistry)
    monkeypatch.setattr(tracking, "record_upload", lambda **kw: calls["record"].append(kw))
    monkeypatch.setattr(tracking, "update_upload_status", lambda st, status: calls["status"].append((st, status)))

    async def app_with_identity(scope, receive, send):
        if scope["type"] == "http" and calls["identity"] is not None:
            scope.setdefault("state", {})["km_identity"] = calls["identity"]
        await web.app(scope, receive, send)

    return TestClient(app_with_identity, raise_server_exceptions=False), calls, tmp_path


def _upload(test_client):
    return test_client.post("/api/ui/upload/ingest?extraction_mode=wifi", files={"file": ("notes.md", b"# notes\n", "text/markdown")})


def test_upload_without_session_is_rejected(client):
    test_client, calls, _ = client
    calls["identity"] = None
    response = _upload(test_client)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "session_required"
    assert calls["record"] == [] and calls["status"] == []


def test_session_for_other_zone_is_rejected(client):
    test_client, calls, _ = client
    calls["identity"] = {"instance_id": "da40"}
    assert _upload(test_client).status_code == 401
    assert calls["record"] == []


def test_queued_upload_is_recorded(client):
    test_client, calls, tmp_path = client
    response = _upload(test_client)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "submitted" and body["data_zone"] == "TEST" and body["duplicate"] is False
    assert len(calls["record"]) == 1
    record = calls["record"][0]
    assert record["status"] == "queued" and record["data_zone"] == "TEST" and record["task_id"] == body["task_id"]
    assert record["file_name"] == "notes.md" and record["file_hash"] == body["file_hash"]
    assert calls["status"] == []
    assert list((tmp_path / ".staging").iterdir()) == []


def test_queue_failure_marks_upload_queue_failed(client):
    test_client, calls, tmp_path = client
    calls["queue_error"] = ConnectionError("redis unavailable")
    response = _upload(test_client)
    assert response.status_code == 500
    assert len(calls["record"]) == 1
    assert [status for _, status in calls["status"]] == ["queue_failed"]
    state = calls["status"][0][0]
    assert state["ui_session_upload"] is True and state["data_zone"] == "TEST"
    assert "ingest_failed" in calls["registry"]
