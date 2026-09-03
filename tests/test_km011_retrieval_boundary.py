from src.retrieval_contract import resolve_retrieval_mode, retrieval_backend
from pathlib import Path


def test_km011_canonical_mode_mapping():
    assert resolve_retrieval_mode("basic") == "vector"
    assert resolve_retrieval_mode("rag") == "vector"
    assert resolve_retrieval_mode("deep") == "deep"
    assert resolve_retrieval_mode("graphrag") == "deep"
    assert resolve_retrieval_mode("hybrid") == "hybrid"
    assert resolve_retrieval_mode("auto") == "auto"


def test_km011_backend_contract():
    assert retrieval_backend("vector") == "qdrant"
    assert retrieval_backend("deep") == "neo4j"
    assert retrieval_backend("hybrid") == "qdrant+neo4j"
    assert retrieval_backend("auto") == "router"


def test_unified_search_does_not_route_basic_to_legacy_neo4j_search():
    source = Path("src/search/__init__.py").read_text(encoding="utf-8")
    tail = source[source.index("    def search("):]
    assert 'if mode == "vector":' in tail
    assert 'self.vector_search(query, top_k=top_k)' in tail
    assert 'self.basic_search(query, top_k=top_k)' not in tail
