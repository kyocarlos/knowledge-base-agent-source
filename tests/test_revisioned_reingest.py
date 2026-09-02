from pathlib import Path

from src.ingest_registry import IngestRegistry
from src.knowledge_lifecycle import KnowledgeLifecycle
from src.revisioned_reingest import reingest_revision


def _metadata(version: str) -> dict:
    return {
        "package_id": f"pkg-doc-1-{version}",
        "document_id": "doc-1",
        "document_version": version,
    }


def _published_v1(tmp_path: Path) -> tuple[KnowledgeLifecycle, dict]:
    lifecycle = KnowledgeLifecycle(IngestRegistry(tmp_path / "registry.sqlite3"))
    first = lifecycle.register(_metadata("1.0.0"))
    lifecycle.transition(first["package_id"], "ready")
    lifecycle.publish(first["package_id"])
    return lifecycle, first


def test_failed_processing_keeps_previous_current_and_revision_unpublished(tmp_path: Path):
    lifecycle, first = _published_v1(tmp_path)
    second = lifecycle.register(_metadata("2.0.0"))

    result = reingest_revision(
        lifecycle,
        second["package_id"],
        lambda: (_ for _ in ()).throw(RuntimeError("injected processing failure")),
    )

    assert result.published is False
    assert lifecycle.get(second["package_id"])["publish_status"] == "draft"
    assert lifecycle.get(second["package_id"])["is_current"] is False
    assert lifecycle.get(first["package_id"])["publish_status"] == "published"
    assert lifecycle.get(first["package_id"])["is_current"] is True


def test_store_failure_keeps_previous_current_and_allows_retry(tmp_path: Path):
    lifecycle, first = _published_v1(tmp_path)
    second = lifecycle.register(_metadata("2.0.0"))
    calls = []

    class FailingStore:
        def set_package_visibility(self, *_args):
            calls.append("failed")
            return False

    failed = reingest_revision(
        lifecycle,
        second["package_id"],
        lambda: calls.append("indexed"),
        vector_store=FailingStore(),
    )

    assert failed.published is False
    assert lifecycle.get(second["package_id"])["publish_status"] == "ready"
    assert lifecycle.get(first["package_id"])["is_current"] is True

    succeeded = reingest_revision(
        lifecycle,
        second["package_id"],
        lambda: calls.append("retried"),
    )

    assert succeeded.published is True
    assert lifecycle.get(second["package_id"])["is_current"] is True
    assert lifecycle.get(first["package_id"])["publish_status"] == "superseded"
    assert calls[0] == "indexed"
    assert "retried" in calls


def test_reingest_module_is_the_application_integration_boundary():
    from src.ingest import reingest_document_revision

    assert callable(reingest_document_revision)
