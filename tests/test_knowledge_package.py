import json

import pytest
from unittest.mock import MagicMock, patch

from src.chunker import chunk_document
from src.knowledge_package import (
    build_chunk_id,
    build_package_id,
    build_package_metadata,
    resolve_document_version,
)


def test_package_and_chunk_identity_are_revision_scoped():
    package = build_package_metadata(
        document_id="doc-1",
        document_version="2.0.0",
        content_hash="a" * 64,
    )
    assert package["package_schema_version"] == "1.0"
    assert package["package_id"] == build_package_id("doc-1", "2.0.0")
    assert build_chunk_id("doc-1", "1.0.0", 0, "same") != build_chunk_id("doc-1", "2.0.0", 0, "same")


def test_document_version_rejects_ambiguous_values():
    assert resolve_document_version({}) == "1.0.0"
    assert resolve_document_version({"documentVersion": "2"}) == "2"
    with pytest.raises(ValueError):
        resolve_document_version({"document_version": "latest"})


def test_real_chunking_emits_package_metadata(tmp_path):
    document = tmp_path / "real-document.md"
    document.write_text("# Heading\n\n" + "A" * 140, encoding="utf-8")
    (tmp_path / "real-document.source.json").write_text(
        json.dumps({"document_id": "doc-real", "document_version": "3.1.0"}),
        encoding="utf-8",
    )

    chunks = chunk_document(str(document))

    assert chunks
    assert [chunk["chunk_index"] for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk["metadata"]["document_id"] == "doc-real" for chunk in chunks)
    assert all(chunk["metadata"]["document_version"] == "3.1.0" for chunk in chunks)
    assert len({chunk["id"] for chunk in chunks}) == len(chunks)


def test_qdrant_point_id_is_uuid_and_chunk_identity_is_payload():
    from src.vector_store import VectorStore

    store = object.__new__(VectorStore)
    store.available = True
    store.client = MagicMock()
    store.model = MagicMock()
    store.model.encode.return_value.tolist.return_value = [[0.0] * store.VECTOR_DIM]
    store._ensure_collection = MagicMock()
    document = {
        "id": "doc@1.0.0::chunk::0::abcdef",
        "content": "content",
        "metadata": {"chunk_id": "doc@1.0.0::chunk::0::abcdef"},
    }
    with patch("src.vector_store.uuid.uuid5") as uuid5:
        uuid5.return_value = "00000000-0000-0000-0000-000000000001"
        assert store.add_documents([document], "doc") is True
        point = store.client.upsert.call_args.kwargs["points"][0]
        assert point.id == "00000000-0000-0000-0000-000000000001"
        assert point.payload["chunk_id"] == document["metadata"]["chunk_id"]


def test_search_source_projection_preserves_package_identity():
    from src.search import SearchEngine

    engine = object.__new__(SearchEngine)
    engine.default_basic_top_k = 3
    engine.vector_store = MagicMock()
    engine.vector_store.search.return_value = [{
        "doc_name": "doc-real",
        "content": "retrievable content",
        "score": 0.9,
        "chunk_index": 0,
        "document_id": "doc-real",
        "package_id": "package-real",
        "document_version": "3.1.0",
        "chunk_id": "doc-real@3.1.0::chunk::0::abc",
        "publish_status": "draft",
        "is_current": False,
    }]
    engine._extract_case_hints = lambda query: []
    engine._is_numeric_extraction_query = lambda query: False
    engine._rank_vector_results = lambda results, query, top_k: results
    result = engine._vector_search_raw("retrievable content")
    source = result["sources"][0]
    assert source["package_id"] == "package-real"
    assert source["document_version"] == "3.1.0"
    assert source["chunk_id"] == "doc-real@3.1.0::chunk::0::abc"
