from pathlib import Path

import pytest

from src.ingest_registry import IngestRegistry
from src.knowledge_lifecycle import (
    KnowledgeLifecycle,
    LifecycleConflict,
    StoreConsistencyError,
)


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

    with pytest.raises(StoreConsistencyError, match="Qdrant") as raised:
        lifecycle.publish(item["package_id"], vector_store=FailingStore())
    assert lifecycle.get(item["package_id"])["publish_status"] == "ready"
    assert raised.value.partial_write is False


class RecordingStore:
    def __init__(self, fail_package_id: str | None = None):
        self.fail_package_id = fail_package_id
        self.state: dict[str, tuple[str, bool]] = {}

    def set_package_visibility(self, package_id, status, is_current):
        if package_id == self.fail_package_id:
            return False
        self.state[package_id] = (status, is_current)
        return True


def _ready_revision(lifecycle, version):
    item = lifecycle.register(metadata(version=version))
    lifecycle.transition(item["package_id"], "ready")
    return item


def _published_pair(tmp_path: Path):
    lifecycle = KnowledgeLifecycle(IngestRegistry(tmp_path / "registry.sqlite3"))
    qdrant = RecordingStore()
    neo4j = RecordingStore()
    first = _ready_revision(lifecycle, "1.0.0")
    lifecycle.publish(first["package_id"], vector_store=qdrant, graph_writer=neo4j)
    second = _ready_revision(lifecycle, "2.0.0")
    return lifecycle, qdrant, neo4j, first, second


def test_qdrant_success_neo4j_failure_is_identifiable_and_recoverable(tmp_path: Path):
    lifecycle, qdrant, _, first, second = _published_pair(tmp_path)
    neo4j = RecordingStore(fail_package_id=second["package_id"])

    with pytest.raises(StoreConsistencyError) as raised:
        lifecycle.publish(second["package_id"], vector_store=qdrant, graph_writer=neo4j)

    error = raised.value
    assert error.partial_write is True
    assert error.rollback_complete is True
    assert error.store_outcomes[f"qdrant:{second['package_id']}"] == "applied"
    assert error.store_outcomes[f"neo4j:{second['package_id']}"] == "failed"
    assert lifecycle.get(first["package_id"])["is_current"] is True
    assert lifecycle.get(second["package_id"])["publish_status"] == "ready"

    neo4j.fail_package_id = None
    lifecycle.publish(second["package_id"], vector_store=qdrant, graph_writer=neo4j)
    assert lifecycle.get(second["package_id"])["is_current"] is True


def test_neo4j_success_qdrant_failure_is_identifiable_and_recoverable(tmp_path: Path):
    lifecycle, _, neo4j, first, second = _published_pair(tmp_path)
    qdrant = RecordingStore(fail_package_id=second["package_id"])

    with pytest.raises(StoreConsistencyError) as raised:
        lifecycle.publish(second["package_id"], vector_store=qdrant, graph_writer=neo4j)

    error = raised.value
    assert error.partial_write is True
    assert error.rollback_complete is True
    assert error.store_outcomes[f"qdrant:{second['package_id']}"] == "failed"
    assert error.store_outcomes[f"neo4j:{second['package_id']}"] == "applied"
    assert lifecycle.get(first["package_id"])["is_current"] is True
    assert lifecycle.get(second["package_id"])["publish_status"] == "ready"

    qdrant.fail_package_id = None
    lifecycle.publish(second["package_id"], vector_store=qdrant, graph_writer=neo4j)
    assert lifecycle.get(second["package_id"])["is_current"] is True
