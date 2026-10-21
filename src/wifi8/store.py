"""Qdrant-backed store for imported Wi-Fi8 packages (no local database).

Two collections in the KM data zone's own Qdrant hold everything:

* chunks collection: one point per retrieval chunk with a dense vector (``dense``),
  a BM25 sparse vector (``text``, IDF applied by Qdrant) and the chunk/document payload.
  ``packages`` lists every package the point belongs to, so a new package can be
  staged next to the serving one and unchanged chunks are shared.
* documents collection: one point per (package, document) plus one package record
  holding the manifest and counts.
"""
from __future__ import annotations

import uuid
from typing import Any, Iterable

DENSE = "dense"
SPARSE = "text"
RECORD_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "km/wifi8/record")


def document_point_id(package_id: str, revision_id: str) -> str:
    return str(uuid.uuid5(RECORD_NAMESPACE, f"document/{package_id}/{revision_id}"))


def package_point_id(package_id: str) -> str:
    return str(uuid.uuid5(RECORD_NAMESPACE, f"package/{package_id}"))


def match(key: str, value: Any):
    from qdrant_client.models import FieldCondition, MatchValue
    return FieldCondition(key=key, match=MatchValue(value=value))


def scroll_all(qdrant, collection: str, flt, *, payload=True, batch: int = 512) -> Iterable[Any]:
    offset = None
    while True:
        points, offset = qdrant.scroll(collection, scroll_filter=flt, limit=batch, offset=offset,
                                       with_payload=payload, with_vectors=False)
        yield from points
        if offset is None:
            return


class Wifi8Store:
    """Read access to one package; documents are cached because a package never changes."""

    def __init__(self, qdrant, *, package_id: str, chunks_collection: str, documents_collection: str):
        self.qdrant = qdrant
        self.package_id = package_id
        self.chunks_collection = chunks_collection
        self.documents_collection = documents_collection
        self._documents: list[dict[str, Any]] | None = None
        self._record: dict[str, Any] | None = None

    def chunk_filter(self, *extra):
        from qdrant_client.models import Filter
        return Filter(must=[match("packages", self.package_id), *extra])

    def record(self) -> dict[str, Any]:
        if self._record is None:
            found = self.qdrant.retrieve(self.documents_collection, ids=[package_point_id(self.package_id)], with_payload=True)
            if not found:
                raise LookupError(f"package record {self.package_id} not found in {self.documents_collection}")
            self._record = found[0].payload or {}
        return self._record

    # ---- package -------------------------------------------------------
    def manifest(self) -> dict[str, Any]:
        return self.record().get("manifest") or {}

    def counts(self) -> dict[str, int]:
        total = self.qdrant.count(self.chunks_collection, count_filter=self.chunk_filter(), exact=True).count
        pending = self.qdrant.count(self.chunks_collection, count_filter=self.chunk_filter(match("vector_state", "pending")),
                                    exact=True).count
        documents = self.documents()
        return {
            "documents": len(documents),
            "documents_analysis_eligible": sum(1 for d in documents if d.get("analysis_eligible")),
            "segments": int(self.record().get("segments") or 0),
            "chunks": total,
            "chunks_pending": pending,
            "chunks_ready": total - pending,
        }

    # ---- documents -----------------------------------------------------
    def documents(self) -> list[dict[str, Any]]:
        if self._documents is None:
            from qdrant_client.models import Filter
            flt = Filter(must=[match("package_id", self.package_id), match("kind", "document")])
            docs = [p.payload["document"] for p in scroll_all(self.qdrant, self.documents_collection, flt)]
            self._documents = sorted(docs, key=lambda d: d["revision_id"])
        return self._documents

    def document(self, revision_id: str) -> dict[str, Any] | None:
        return next((d for d in self.documents() if d["revision_id"] == revision_id), None)

    # ---- chunks --------------------------------------------------------
    def chunks(self, point_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not point_ids:
            return {}
        points = self.qdrant.retrieve(self.chunks_collection, ids=list(point_ids), with_payload=True)
        return {str(p.id): p.payload for p in points if self.package_id in ((p.payload or {}).get("packages") or [])}

    def chunk_page(self, revision_id: str, start: int, count: int, *, figures: bool = False) -> tuple[int, list[tuple[str, dict[str, Any]]]]:
        """(total chunks of the document, [(point_id, payload)] ordered by chunk_index from ``start``);
        ``figures`` limits both to the chunks made from the document's figures."""
        from qdrant_client.models import FieldCondition, Filter, IsEmptyCondition, OrderBy, PayloadField, Range
        must = [match("packages", self.package_id), match("revision_id", revision_id)]
        must_not = [IsEmptyCondition(is_empty=PayloadField(key="image_id"))] if figures else None
        total = self.qdrant.count(self.chunks_collection, count_filter=Filter(must=must, must_not=must_not), exact=True).count
        page = Filter(must=[*must, FieldCondition(key="chunk_index", range=Range(gte=start))], must_not=must_not)
        points, _ = self.qdrant.scroll(self.chunks_collection, scroll_filter=page, limit=count, with_payload=True,
                                       with_vectors=False, order_by=OrderBy(key="chunk_index"))
        return total, [(str(p.id), p.payload) for p in points]
