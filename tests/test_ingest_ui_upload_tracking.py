"""ingest_file_task keeps UI upload tracking in sync: completed / retrying / failed."""
from __future__ import annotations

import pytest


@pytest.fixture()
def harness(monkeypatch, tmp_path):
    from src.web_api import tasks
    import src.converter
    import src.ingest
    import src.index_generator
    import src.ui_upload_tracking as tracking

    original = tmp_path / "upload" / "notes.md"
    original.parent.mkdir()
    original.write_text("# notes\n", encoding="utf-8")
    state = {
        "task_id": "t-1", "original_path": str(original), "converted_path": str(tmp_path / "converted" / "notes.md"),
        "extraction_mode": "simple", "file_hash": "a" * 64, "file_name": "notes.md", "data_zone": "test",
        "ui_session_upload": True,
    }
    calls = {"record": [], "status": [], "ingest_error": None}

    class FakeConverter:
        def convert_file(self, src, dst):
            from pathlib import Path
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_text("converted", encoding="utf-8")
            return {"status": "success", "image_refs": []}

    def fake_ingest(*args, **kwargs):
        if calls["ingest_error"] is not None:
            raise calls["ingest_error"]
        return True

    monkeypatch.setattr(tasks, "get_ingest_task_state", lambda task_id: dict(state))
    monkeypatch.setattr(tasks, "update_ingest_task_state", lambda task_id, **kw: {"task_id": task_id, **kw})
    monkeypatch.setattr(tasks, "_write_source_metadata", lambda *a, **k: None)
    monkeypatch.setattr(src.converter, "FileConverter", FakeConverter)
    monkeypatch.setattr(src.ingest, "ingest_document", fake_ingest)
    monkeypatch.setattr(src.index_generator, "generate_index_md", lambda *a, **k: None)
    monkeypatch.setattr(tracking, "record_upload", lambda **kw: calls["record"].append(kw))
    monkeypatch.setattr(tracking, "update_upload_status", lambda st, status: calls["status"].append(status))
    return tasks, state, calls


def test_completed_upload_is_recorded(harness):
    tasks, state, calls = harness
    result = tasks.ingest_file_task.run("t-1")
    assert result["status"] == "completed"
    assert len(calls["record"]) == 1
    record = calls["record"][0]
    assert record["status"] == "completed" and record["data_zone"] == "test" and record["file_hash"] == "a" * 64
    assert calls["status"] == []


def test_retryable_error_marks_upload_retrying(harness):
    tasks, state, calls = harness
    calls["ingest_error"] = ConnectionError("neo4j unavailable")
    with pytest.raises(Exception):
        tasks.ingest_file_task.run("t-1")
    assert calls["status"] == ["retrying"] and calls["record"] == []


def test_non_retryable_error_marks_upload_failed(harness):
    tasks, state, calls = harness
    calls["ingest_error"] = ValueError("bad document")
    tasks.ingest_file_task.run("t-1")
    assert calls["status"] == ["failed"] and calls["record"] == []


def test_non_ui_upload_is_not_tracked(harness, monkeypatch):
    tasks, state, calls = harness
    monkeypatch.setattr(tasks, "get_ingest_task_state", lambda task_id: {**state, "ui_session_upload": False})
    tasks.ingest_file_task.run("t-1")
    calls["ingest_error"] = ValueError("bad document")
    tasks.ingest_file_task.run("t-1")
    assert calls["record"] == [] and calls["status"] == []
