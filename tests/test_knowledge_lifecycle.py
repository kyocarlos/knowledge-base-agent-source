from pathlib import Path

import pytest

from src.ingest_registry import IngestRegistry
from src.knowledge_lifecycle import KnowledgeLifecycle, LifecycleConflict


def metadata(document_id="doc-1", version="1.0.0"):
    return {
        "package_id": f"{document_id}:{version}",
        "document_id": document_id,
        "document_version": version,
    }


def test_transitions_are_durable_and_ordered(tmp_path: Path):
    lifecycle = KnowledgeLifecycle(IngestRegistry(tmp_path / "registry.sqlite3"))
    item = lifecycle.register(metadata())
    assert item["publish_status"] == "draft"
    assert lifecycle.transition(item["package_id"], "ready")["publish_status"] == "ready"
    with pytest.raises(LifecycleConflict):
        lifecycle.transition(item["package_id"], "superseded")


def test_publish_promotes_current_and_supersedes_prior(tmp_path: Path):
    lifecycle = KnowledgeLifecycle(IngestRegistry(tmp_path / "registry.sqlite3"))
    first = lifecycle.register(metadata(version="1.0.0"))
    lifecycle.transition(first["package_id"], "ready")
    lifecycle.publish(first["package_id"])
    second = lifecycle.register(metadata(version="2.0.0"))
    lifecycle.transition(second["package_id"], "ready")
    lifecycle.publish(second["package_id"])
    assert lifecycle.get(second["package_id"])["is_current"] is True
    assert lifecycle.get(first["package_id"])["publish_status"] == "superseded"
    assert lifecycle.get(first["package_id"])["is_current"] is False


def test_failed_store_update_does_not_advance_registry(tmp_path: Path):
    lifecycle = KnowledgeLifecycle(IngestRegistry(tmp_path / "registry.sqlite3"))
    item = lifecycle.register(metadata())
    lifecycle.transition(item["package_id"], "ready")

    class FailingStore:
        def set_package_visibility(self, *_args):
            return False

    with pytest.raises(RuntimeError, match="Qdrant"):
        lifecycle.publish(item["package_id"], vector_store=FailingStore())
    assert lifecycle.get(item["package_id"])["publish_status"] == "ready"
