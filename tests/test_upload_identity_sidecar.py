"""Upload identity reaches Qdrant/Neo4j metadata while doc_name stays the file stem."""
from __future__ import annotations

import json

import pytest

IDENTITY = {
    "source_system": "KM_UI", "environment_id": "TEST", "project_id": "KM_UI", "run_id": "ui-1",
    "artifact_type": "document", "original_file_name": "notes.md", "source_file_hash": "a" * 64,
    "ingest_file_hash": "a" * 64, "document_id": "kmui-abc", "idempotency_key": "kmui-key",
    "generated_at": "2026-10-15T00:00:00",
}


def _sidecar(path):
    return path.with_name(f"{path.stem}.source.json")


def test_converted_sidecar_gets_identity(tmp_path):
    from src.web_api.tasks import _write_converted_identity
    converted = tmp_path / "notes.md"
    _write_converted_identity(converted, {**IDENTITY, "task_id": "t-1", "content": "x"})
    data = json.loads(_sidecar(converted).read_text(encoding="utf-8"))
    assert data == IDENTITY


def test_canonical_report_fields_win(tmp_path):
    from src.web_api.tasks import _write_converted_identity
    converted = tmp_path / "report.md"
    _sidecar(converted).write_text(json.dumps({"run_id": "RUN-REAL", "environment": "lab-a", "storage_category": "Report"}), encoding="utf-8")
    _write_converted_identity(converted, {**IDENTITY, "environment": "other"})
    data = json.loads(_sidecar(converted).read_text(encoding="utf-8"))
    assert data["run_id"] == "RUN-REAL" and data["environment"] == "lab-a" and data["storage_category"] == "Report"
    assert data["document_id"] == "kmui-abc" and data["original_file_name"] == "notes.md"


def test_legacy_upload_without_identity_writes_nothing(tmp_path):
    from src.web_api.tasks import _write_converted_identity
    converted = tmp_path / "legacy.md"
    _write_converted_identity(converted, {"task_id": "t-1", "file_hash": "b" * 64})
    assert not _sidecar(converted).exists()


def test_ingest_task_writes_identity_before_ingest(monkeypatch, tmp_path):
    from pathlib import Path
    from src.web_api import tasks
    import src.converter
    import src.ingest
    import src.index_generator

    original = tmp_path / "upload" / "original" / "notes.md"
    original.parent.mkdir(parents=True)
    original.write_text("# notes\n", encoding="utf-8")
    converted = tmp_path / "upload" / "converted" / "notes.md"
    state = {"task_id": "t-1", "original_path": str(original), "converted_path": str(converted),
             "extraction_mode": "lab", "file_hash": "a" * 64, "file_name": "notes.md", **IDENTITY}
    seen = {}

    class FakeConverter:
        def convert_file(self, src, dst):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_text("converted", encoding="utf-8")
            return {"status": "success", "image_refs": []}

    def fake_ingest(doc_path, *args, **kwargs):
        seen["doc_path"] = doc_path
        seen["sidecar"] = json.loads(_sidecar(Path(doc_path)).read_text(encoding="utf-8"))
        return True

    monkeypatch.setattr(tasks, "get_ingest_task_state", lambda task_id: dict(state))
    monkeypatch.setattr(tasks, "update_ingest_task_state", lambda task_id, **kw: {"task_id": task_id, **kw})
    monkeypatch.setattr(tasks, "acquire_document_lock", lambda *a, **k: True)
    monkeypatch.setattr(tasks, "release_document_lock", lambda *a, **k: True)
    monkeypatch.setattr(tasks, "_write_source_metadata", lambda *a, **k: None)
    monkeypatch.setattr("src.ingest_registry.IngestRegistry", lambda *a, **k: type("R", (), {"record_event": lambda *a, **k: None, "update_status": lambda *a, **k: None})())
    monkeypatch.setattr(src.converter, "FileConverter", FakeConverter)
    monkeypatch.setattr(src.ingest, "ingest_document", fake_ingest)
    monkeypatch.setattr(src.index_generator, "generate_index_md", lambda *a, **k: None)
    assert tasks.ingest_file_task.run("t-1")["status"] == "completed"
    assert seen["doc_path"] == str(converted)
    assert seen["sidecar"]["document_id"] == "kmui-abc" and seen["sidecar"]["original_file_name"] == "notes.md"


@pytest.fixture()
def converted_doc(tmp_path):
    from src.web_api.tasks import _write_converted_identity
    doc = tmp_path / "Lab" / "t-1" / "converted" / "zz-notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# 標題\n\n" + "這是一段用來切塊的測試內容，包含足夠的文字。\n" * 40, encoding="utf-8")
    _write_converted_identity(doc, IDENTITY)
    return doc


def test_vector_doc_name_is_stem_and_chunks_carry_identity(monkeypatch, converted_doc):
    import src.ingest as ingest
    import src.vector_store as vector_store
    captured = {}

    class FakeStore:
        def add_documents(self, chunks, doc_name):
            captured.update(chunks=chunks, doc_name=doc_name)

    monkeypatch.setattr(vector_store, "get_vector_store", lambda: FakeStore())
    assert ingest.ingest_vector(str(converted_doc), storage_category="Lab")
    assert captured["doc_name"] == "zz-notes"
    assert captured["chunks"]
    for chunk in captured["chunks"]:
        assert chunk["metadata"]["document_id"] == "kmui-abc"
        assert chunk["metadata"]["original_file_name"] == "notes.md"
        assert chunk["metadata"]["idempotency_key"] == "kmui-key"


def test_ingest_document_cleans_up_by_stem(monkeypatch, converted_doc):
    import src.ingest as ingest
    calls = {}
    monkeypatch.setattr(ingest, "cleanup_existing_document", lambda name, **kw: calls.setdefault("cleanup", name))
    monkeypatch.setattr(ingest, "ingest_vector", lambda path, storage_category=None: calls.setdefault("vector", path) or True)
    assert ingest.ingest_document(str(converted_doc), extraction_mode="lab")
    assert calls["cleanup"] == "zz-notes"
