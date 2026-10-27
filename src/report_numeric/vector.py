"""Qdrant side: one collection (ai_km_knowledge_v1), deterministic point ids, the Qdrant payload spec's required fields, dense + BM25 sparse vectors."""
from __future__ import annotations

import uuid
from typing import Any, Callable

from .timescale import POLICY

COLLECTION = "ai_km_knowledge_v1"
DENSE, SPARSE = "dense", "text"
NAMESPACE = uuid.UUID("0c7b8a6e-3d2f-4b8e-9d7e-5a1f9c2b7e41")
KEYWORD_INDEXES = ("document_id", "document_version", "content_type", "product_id", "report_type", "band", "test_run_id", "approval_status", "publish_status", "visibility", "access_roles")
INTEGER_INDEXES = ("bandwidth_mhz", "channel")


def point_id(document_id: str, version: str, chunk_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{document_id}|{version}|{chunk_id}"))


def ensure_collection(client, dim: int = 768) -> None:
    from qdrant_client.models import Distance, Modifier, PayloadSchemaType, SparseVectorParams, VectorParams
    if not client.collection_exists(COLLECTION):
        client.create_collection(COLLECTION, vectors_config={DENSE: VectorParams(size=dim, distance=Distance.COSINE)},
                                 sparse_vectors_config={SPARSE: SparseVectorParams(modifier=Modifier.IDF)})
    for field in KEYWORD_INDEXES:
        client.create_payload_index(COLLECTION, field, field_schema=PayloadSchemaType.KEYWORD)
    for field in INTEGER_INDEXES:
        client.create_payload_index(COLLECTION, field, field_schema=PayloadSchemaType.INTEGER)


def payload(pkg: dict, chunk: dict, model: str, model_version: str) -> dict:
    doc, run = pkg["document"], pkg["test_run"]
    return {
        "schema_version": pkg["schema_version"], "document_id": doc["document_id"], "document_version": doc["document_version"], "chunk_id": chunk["chunk_id"],
        "chunk_index": chunk["chunk_index"], "chunk_hash": chunk["chunk_hash"], "chunk_text": chunk["text"], "source_system": POLICY["source_system"],
        "source_record_id": doc["document_id"], "title": doc["title"] or doc["document_id"], "document_type": "test_report", "publish_status": POLICY["publish_status"],
        "approval_status": POLICY["approval_status"], "approval_basis": POLICY["approval_basis"], "is_current": True, "visibility": POLICY["visibility"],
        "owner_department": POLICY["owner_department"], "access_roles": POLICY["access_roles"], "access_departments": POLICY["access_departments"],
        "embedding_model": model, "embedding_model_version": model_version,
        "content_type": chunk["content_type"], "report_type": doc["report_type"], "product_id": run["product_id"], "dut_model": run["dut_model"],
        "firmware_version": run.get("firmware_version"), "test_run_id": run["test_run_id"], "band": chunk.get("band"), "bandwidth_mhz": chunk.get("bandwidth_mhz"),
        "channel": chunk.get("channel"), "test_case_id": chunk.get("test_case_id"), "source_sheet": chunk.get("source_sheet"), "source_cell_range": chunk.get("source_cell_range"),
        "numeric_ref": f"km_test.test_run/{run['test_run_id']}",
    }


def write_chunks(client, pkg: dict, chunks: list[dict], encode: Callable[[list[str]], list[list[float]]], sparse: Callable[[str], tuple[list[int], list[float]]],
                 model: str, model_version: str, batch: int = 32) -> int:
    from qdrant_client.models import PointStruct, SparseVector
    doc = pkg["document"]
    ensure_collection(client)
    # Re-ingest replaces the report's points: ids are deterministic, and chunks that no longer exist are removed.
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    client.delete(COLLECTION, points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=doc["document_id"])),
                                                           FieldCondition(key="document_version", match=MatchValue(value=doc["document_version"]))]), wait=True)
    total = 0
    for i in range(0, len(chunks), batch):
        part = chunks[i:i + batch]
        vectors = encode([c["text"] for c in part])
        points = []
        for c, v in zip(part, vectors):
            idx, vals = sparse(c["text"])
            points.append(PointStruct(id=point_id(doc["document_id"], doc["document_version"], c["chunk_id"]),
                                      vector={DENSE: list(map(float, v)), SPARSE: SparseVector(indices=idx, values=vals)}, payload=payload(pkg, c, model, model_version)))
        client.upsert(COLLECTION, points=points, wait=True)
        total += len(points)
    return total


def doc_sparse(text: str) -> tuple[list[int], list[float]]:
    """BM25-style term weights with the same hashing as the WiFi zone, so one tokenizer serves both."""
    from src.wifi8.lexical import document_vector
    return document_vector(text, "", avg_tokens=60.0)


def query_sparse(text: str) -> tuple[list[int], list[float]]:
    from src.wifi8.lexical import query_terms, term_index
    idx = sorted({term_index(t) for t in query_terms(text)})
    return idx, [1.0] * len(idx)


def load_encoder(model_name: str | None = None):
    """Embedding model (CPU) without touching any production Qdrant collection. Returns (name, encode, count_tokens)."""
    import os
    from sentence_transformers import SentenceTransformer
    name = model_name or os.environ.get("KM_EMBEDDING_MODEL", "BAAI/bge-base-zh-v1.5")
    model = SentenceTransformer(name, device="cpu")
    tok = model.tokenizer
    return (name, lambda texts: model.encode(list(texts), normalize_embeddings=True).tolist(),
            lambda t: len(tok(t, add_special_tokens=False)["input_ids"]))
