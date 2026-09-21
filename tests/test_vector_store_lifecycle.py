from __future__ import annotations

from src.vector_store import VectorStore


class _FakeClient:
    def __init__(self) -> None:
        self.points = []

    def upsert(self, *, collection_name, points):
        self.points.extend(points)


def _store() -> tuple[VectorStore, _FakeClient]:
    client = _FakeClient()
    store = VectorStore.__new__(VectorStore)
    store.available = True
    store.client = client
    store.model_name = "embedding-test"
    store.encode = lambda texts: [[0.1, 0.2] for _ in texts]
    store._ensure_collection = lambda: None
    return store, client


def test_report_lifecycle_defaults_fail_closed_in_both_payload_locations() -> None:
    store, client = _store()

    assert store.add_documents(
        [{"content": "report content", "metadata": {"extraction_mode": "report"}}],
        "report",
    )

    payload = client.points[0].payload
    assert payload["publish_status"] == "draft"
    assert payload["is_current"] is False
    assert payload["metadata"]["publish_status"] == "draft"
    assert payload["metadata"]["is_current"] is False


def test_ordinary_document_lifecycle_defaults_are_consistent() -> None:
    store, client = _store()

    assert store.add_documents([{"content": "knowledge", "metadata": {}}], "doc")

    payload = client.points[0].payload
    # Formal ingest is fail-closed.  A separate technical publication
    # transaction must promote a draft; ordinary writes must not become
    # searchable merely because they reached Qdrant.
    assert payload["publish_status"] == "draft"
    assert payload["is_current"] is False
    assert payload["metadata"]["publish_status"] == "draft"
    assert payload["metadata"]["is_current"] is False
