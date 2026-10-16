"""Hybrid retrieval for the WiFi zone: full-text (BM25 sparse vectors) + dense vectors, fused by RRF.

Both retrievers run in the data zone's Qdrant. Follows the Wi-Fi8 KM System approach:
lexical matching of technical terms, explicit publisher / WFA document id filters,
current-version policy by default, and a per-document cap so one large document
cannot crowd out the rest.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from . import store as store_module
from .lexical import query_terms, query_vector

RRF_K = 60
_WFA_ID = re.compile(r"(?<!\d)\d{5,6}(?!\d)")


@dataclass(frozen=True)
class SearchOptions:
    top_k: int = 8
    per_document: int = 3
    candidates: int = 50
    include_history: bool = False
    publishers: tuple[str, ...] = ()
    document_roles: tuple[str, ...] = ()
    revision_ids: tuple[str, ...] = ()


class SearchUnavailable(RuntimeError):
    pass


class Wifi8Search:
    def __init__(self, store: store_module.Wifi8Store, *, qdrant=None,
                 encoder: Callable[[list[str]], list[list[float]]] | None = None):
        self.store = store
        self.package_id = store.package_id
        self.collection = store.chunks_collection
        self.qdrant = qdrant or store.qdrant
        self.encoder = encoder

    @classmethod
    def for_current(cls, importer, *, qdrant=None, encoder=None, embedding_model: str = "") -> "Wifi8Search":
        current = importer.current()
        package = importer.current_store(qdrant)
        if not current or package is None or package.qdrant is None:
            raise SearchUnavailable("WiFi 專區尚未匯入資料")
        if current.get("embedding_model") and embedding_model and current["embedding_model"] != embedding_model:
            # Query vectors from another model would silently return unrelated chunks.
            raise SearchUnavailable(f"embedding model mismatch: {embedding_model} != {current['embedding_model']}")
        return cls(package, encoder=encoder)

    # ---- filters ------------------------------------------------------
    def _documents(self) -> dict[str, dict[str, Any]]:
        return {d["revision_id"]: d for d in self.store.documents()}

    def _resolve(self, query: str, options: SearchOptions, documents: dict[str, dict[str, Any]]) -> SearchOptions:
        publishers = set(options.publishers)
        lowered = query.casefold()
        for name in {d.get("publisher") for d in documents.values() if d.get("publisher") and len(d["publisher"]) >= 3}:
            if re.search(r"(?<![a-z0-9])" + re.escape(name.casefold()) + r"(?![a-z0-9])", lowered):
                publishers.add(name)  # a named vendor is an explicit filter, as in Wi-Fi8
        revisions = set(options.revision_ids)
        for wfa_id in _WFA_ID.findall(query):
            revisions |= {rid for rid, d in documents.items() if str(d.get("wfa_document_id") or "") == wfa_id}
        return SearchOptions(**{**options.__dict__, "publishers": tuple(sorted(publishers)), "revision_ids": tuple(sorted(revisions))})

    def _filter(self, options: SearchOptions):
        from qdrant_client.models import FieldCondition, MatchAny
        extra = []
        if not options.include_history:
            extra.append(store_module.match("analysis_eligible", True))
        for key, values in (("publisher", options.publishers), ("document_role", options.document_roles),
                            ("revision_id", options.revision_ids)):
            if values:
                extra.append(FieldCondition(key=key, match=MatchAny(any=list(values))))
        return self.store.chunk_filter(*extra)

    # ---- retrievers ---------------------------------------------------
    def lexical(self, query: str, options: SearchOptions) -> list[str]:
        from qdrant_client.models import SparseVector
        indices, values = query_vector(query)
        if not indices:
            return []
        result = self.qdrant.query_points(self.collection, query=SparseVector(indices=indices, values=values),
                                          using=store_module.SPARSE, query_filter=self._filter(options),
                                          limit=options.candidates, with_payload=False)
        return [str(point.id) for point in result.points]

    def vector(self, query: str, options: SearchOptions) -> list[str]:
        if self.encoder is None:
            return []
        result = self.qdrant.query_points(self.collection, query=list(self.encoder([query])[0]), using=store_module.DENSE,
                                          query_filter=self._filter(options), limit=options.candidates, with_payload=False)
        return [str(point.id) for point in result.points]

    # ---- fusion -------------------------------------------------------
    def search(self, query: str, options: SearchOptions | None = None) -> dict[str, Any]:
        options = self._resolve(query, options or SearchOptions(), self._documents())
        lexical = self.lexical(query, options)
        vector = self.vector(query, options)
        scores: dict[str, float] = {}
        for ranking in (lexical, vector):
            for rank, point_id in enumerate(ranking, 1):
                scores[point_id] = scores.get(point_id, 0.0) + 1.0 / (RRF_K + rank)
        chunks = self.chunks(list(scores))
        per_doc: dict[str, int] = {}
        results = []
        for point_id in sorted(scores, key=lambda pid: (-scores[pid], pid)):
            chunk = chunks.get(point_id)
            if not chunk or per_doc.get(chunk["revision_id"], 0) >= options.per_document:
                continue
            per_doc[chunk["revision_id"]] = per_doc.get(chunk["revision_id"], 0) + 1
            results.append({**chunk, "score": round(scores[point_id], 6),
                            "matched_by": [name for name, r in (("fulltext", lexical), ("vector", vector)) if point_id in r]})
            if len(results) >= options.top_k:
                break
        return {"query": query, "package_id": self.package_id, "terms": query_terms(query),
                "filters": {"publishers": list(options.publishers), "document_roles": list(options.document_roles),
                            "revision_ids": list(options.revision_ids)[:20], "include_history": options.include_history},
                "results": results}

    def chunks(self, point_ids: list[str]) -> dict[str, dict[str, Any]]:
        documents = self._documents()
        result = {}
        for point_id, payload in self.store.chunks(point_ids).items():
            doc = documents.get(payload["revision_id"]) or {}
            result[point_id] = {
                "point_id": point_id, "revision_id": payload["revision_id"], "chunk_index": payload["chunk_index"],
                "source": doc.get("title") or payload.get("doc_name"), "content": payload["content"],
                "location": payload.get("location") or {}, "location_label": payload.get("location_label") or "",
                "segment_ids": payload.get("segment_ids") or [],
                "wfa_document_id": doc.get("wfa_document_id"), "wfa_revision": doc.get("wfa_revision"),
                "document_role": doc.get("document_role"), "publisher": doc.get("publisher"),
                "analysis_eligible": bool(doc.get("analysis_eligible")), "document_date": doc.get("document_date"),
                "storage_category": "WiFi", "source_system": "WIFI8",
            }
        return result
