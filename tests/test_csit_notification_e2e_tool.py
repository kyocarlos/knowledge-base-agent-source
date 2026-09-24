from __future__ import annotations

from src.vector_store import VectorStore


def test_e2e_embedding_is_explicit_and_deterministic(monkeypatch):
    monkeypatch.setenv("KM_E2E_TEST_MODE", "true")
    store = VectorStore.__new__(VectorStore)
    store.model_name = "unused"
    store._init_model()
    first = store.encode(["SCU2060 throughput"])[0]
    second = store.encode(["SCU2060 throughput"])[0]
    assert store.model_name == "km-e2e-deterministic-v1"
    assert len(first) == VectorStore.VECTOR_DIM
    assert first == second
