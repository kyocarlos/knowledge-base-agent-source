"""Hybrid retrieval for the WiFi zone: full-text (trigram BM25) + vector, fused by RRF.

Follows the Wi-Fi8 KM System approach: lexical matching of technical terms,
explicit publisher / WFA document id filters, current-version policy by default,
and a per-document cap so one large document cannot crowd out the rest.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import store

RRF_K = 60
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+/_-]*|[㐀-鿿]+")
_WFA_ID = re.compile(r"(?<!\d)\d{5,6}(?!\d)")
_STOPWORDS = frozenset({
    "the", "and", "for", "what", "how", "with", "from", "that", "this", "are", "is", "of", "in", "to", "a", "an",
    "什麼", "如何", "哪些", "請問", "說明", "介紹", "相關", "資料", "文件", "是否", "可以", "以及", "還有", "知識專區",
})


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


def query_terms(query: str) -> list[str]:
    terms = []
    for token in _TOKEN.findall(query or ""):
        if token.casefold() in _STOPWORDS:
            continue
        if re.fullmatch(r"[㐀-鿿]+", token) and len(token) > 4:
            # Split long CJK runs into overlapping 2-4 char pieces; trigram FTS needs >= 3 chars.
            terms.extend(token[i:i + 3] for i in range(0, len(token) - 2))
        else:
            terms.append(token)
    return list(dict.fromkeys(t for t in terms if t.casefold() not in _STOPWORDS))


def _fts_phrase(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


class Wifi8Search:
    def __init__(self, store_path: Path, *, package_id: str, collection: str, qdrant=None,
                 encoder: Callable[[list[str]], list[list[float]]] | None = None):
        self.store_path = store_path
        self.package_id = package_id
        self.collection = collection
        self.qdrant = qdrant
        self.encoder = encoder

    @classmethod
    def for_current(cls, importer, *, qdrant=None, encoder=None, embedding_model: str = "") -> "Wifi8Search":
        current = importer.current()
        path = importer.current_store()
        if not current or not path:
            raise SearchUnavailable("WiFi 專區尚未匯入資料")
        if qdrant is not None and current.get("embedding_model") and embedding_model and current["embedding_model"] != embedding_model:
            # Query vectors from another model would silently return unrelated chunks.
            raise SearchUnavailable(f"embedding model mismatch: {embedding_model} != {current['embedding_model']}")
        return cls(path, package_id=current["package_id"], collection=current.get("collection") or importer.settings.collection,
                   qdrant=qdrant, encoder=encoder)

    # ---- filters ------------------------------------------------------
    def _documents(self) -> dict[str, dict[str, Any]]:
        with closing(store.connect(self.store_path, readonly=True)) as db:
            return {row["revision_id"]: dict(row) for row in db.execute(
                "SELECT revision_id, title, analysis_eligible, wfa_document_id, document_role, publisher FROM documents")}

    def _resolve(self, query: str, options: SearchOptions, documents: dict[str, dict[str, Any]]) -> SearchOptions:
        publishers = set(options.publishers)
        lowered = query.casefold()
        for name in {d["publisher"] for d in documents.values() if d["publisher"] and len(d["publisher"]) >= 3}:
            if re.search(r"(?<![a-z0-9])" + re.escape(name.casefold()) + r"(?![a-z0-9])", lowered):
                publishers.add(name)  # a named vendor is an explicit filter, as in Wi-Fi8
        revisions = set(options.revision_ids)
        for wfa_id in _WFA_ID.findall(query):
            revisions |= {rid for rid, d in documents.items() if d["wfa_document_id"] == wfa_id}
        return SearchOptions(**{**options.__dict__, "publishers": tuple(sorted(publishers)), "revision_ids": tuple(sorted(revisions))})

    def _allowed(self, doc: dict[str, Any] | None, options: SearchOptions) -> bool:
        if not doc:
            return False
        if not options.include_history and not doc["analysis_eligible"]:
            return False
        if options.publishers and doc["publisher"] not in options.publishers:
            return False
        if options.document_roles and doc["document_role"] not in options.document_roles:
            return False
        if options.revision_ids and doc["revision_id"] not in options.revision_ids:
            return False
        return True

    # ---- retrievers ---------------------------------------------------
    def lexical(self, query: str, options: SearchOptions, documents: dict[str, dict[str, Any]]) -> list[str]:
        terms = query_terms(query)
        long_terms = [t for t in terms if len(t) >= 3]
        short_terms = [t for t in terms if len(t) < 3]
        ranked: list[tuple[float, str]] = []
        with closing(store.connect(self.store_path, readonly=True)) as db:
            if long_terms:
                rows = db.execute(
                    "SELECT f.point_id, bm25(chunks_fts, 2.0, 1.0) AS score, c.revision_id FROM chunks_fts f"
                    " JOIN chunks c ON c.point_id = f.point_id WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?",
                    (" OR ".join(_fts_phrase(t) for t in long_terms), options.candidates * 4)).fetchall()
                ranked += [(row["score"], row["point_id"]) for row in rows if self._allowed(documents.get(row["revision_id"]), options)]
            for term in short_terms:
                # 2-char CJK words fall below the trigram minimum; match them literally.
                pattern = "%" + term.replace("%", "").replace("_", "") + "%"
                rows = db.execute("SELECT point_id, revision_id FROM chunks WHERE text LIKE ? OR revision_id IN"
                                  " (SELECT revision_id FROM documents WHERE title LIKE ?) LIMIT ?",
                                  (pattern, pattern, options.candidates * 2)).fetchall()
                ranked += [(0.0, row["point_id"]) for row in rows if self._allowed(documents.get(row["revision_id"]), options)]
        seen, ordered = set(), []
        for _, point_id in sorted(ranked, key=lambda item: item[0]):
            if point_id not in seen:
                seen.add(point_id)
                ordered.append(point_id)
        return ordered[: options.candidates]

    def vector(self, query: str, options: SearchOptions) -> list[str]:
        if self.qdrant is None or self.encoder is None:
            return []
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
        must = [FieldCondition(key="packages", match=MatchValue(value=self.package_id))]
        if not options.include_history:
            must.append(FieldCondition(key="analysis_eligible", match=MatchValue(value=True)))
        if options.publishers:
            must.append(FieldCondition(key="publisher", match=MatchAny(any=list(options.publishers))))
        if options.document_roles:
            must.append(FieldCondition(key="document_role", match=MatchAny(any=list(options.document_roles))))
        if options.revision_ids:
            must.append(FieldCondition(key="revision_id", match=MatchAny(any=list(options.revision_ids))))
        result = self.qdrant.query_points(self.collection, query=self.encoder([query])[0], query_filter=Filter(must=must),
                                          limit=options.candidates, with_payload=False)
        return [str(point.id) for point in result.points]

    # ---- fusion -------------------------------------------------------
    def search(self, query: str, options: SearchOptions | None = None) -> dict[str, Any]:
        options = options or SearchOptions()
        documents = self._documents()
        options = self._resolve(query, options, documents)
        lexical = self.lexical(query, options, documents)
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
        if not point_ids:
            return {}
        with closing(store.connect(self.store_path, readonly=True)) as db:
            marks = ",".join("?" * len(point_ids))
            rows = db.execute(
                "SELECT c.point_id, c.revision_id, c.ordinal, c.location, c.location_label, c.text, c.segment_ids,"
                " d.title, d.wfa_document_id, d.document_role, d.publisher, d.analysis_eligible, d.data"
                f" FROM chunks c JOIN documents d USING (revision_id) WHERE c.point_id IN ({marks})", point_ids).fetchall()
        result = {}
        for row in rows:
            data = json.loads(row["data"])
            result[row["point_id"]] = {
                "point_id": row["point_id"], "revision_id": row["revision_id"], "chunk_index": row["ordinal"],
                "source": row["title"], "content": row["text"], "location": json.loads(row["location"]),
                "location_label": row["location_label"], "segment_ids": json.loads(row["segment_ids"]),
                "wfa_document_id": row["wfa_document_id"], "wfa_revision": data.get("wfa_revision"),
                "document_role": row["document_role"], "publisher": row["publisher"],
                "analysis_eligible": bool(row["analysis_eligible"]), "document_date": data.get("document_date"),
                "storage_category": "WiFi", "source_system": "WIFI8",
            }
        return result
