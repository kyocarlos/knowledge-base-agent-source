"""Hybrid retrieval for the WiFi zone: full-text (BM25 sparse vectors) + dense vectors, fused by RRF.

Both retrievers run in the data zone's Qdrant. Follows the Wi-Fi8 KM System approach:
lexical matching of technical terms, explicit publisher / WFA document id filters,
current-version policy by default, and a per-document cap so one large document
cannot crowd out the rest.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable

from . import store as store_module
from .excerpt import excerpt
from .lexical import query_terms, query_vector, text_codes, title_codes

RRF_K = 60
# Figure chunks (text made from images) compete with the document text; their fused score is scaled so a related
# diagram does not crowd the passage that answers the question out of the top results (golden set: 1.0 -> hit@10
# 90.0%, 0.7 -> 93.3%). 1.0 disables the scaling.
DEFAULT_IMAGE_WEIGHT = 0.7
# When the question itself asks for a figure (comparison table, timeline, architecture diagram …) the figure chunks are
# what answers it, so they get this weight instead. Terms are matched case-insensitively; KM_WIFI8_FIGURE_TERMS
# (comma-separated) replaces the list. Bare 圖／表 are left out on purpose: 意圖、代表、發表 … are not about figures.
DEFAULT_FIGURE_FOCUS_WEIGHT = 1.3
DEFAULT_FIGURE_TERMS = (
    "比較表", "對照表", "表格", "圖表", "圖片", "圖中", "圖示", "示意圖", "架構圖", "流程圖", "時程圖", "時序圖", "時間軸",
    "截圖", "投影片中的圖", "figure", "diagram", "chart", "timeline", "table",
)


# A question that names a document by its short name ("PF1 Report", "EE1 Report") also matches sibling documents whose
# slides, tables and figure texts are alike but carry other numbers. Chunks of the named documents have their fused
# score multiplied by this weight (1.0 disables it). A name counts only when it is in at most MAX_NAMED_DOCUMENTS titles.
DEFAULT_TITLE_MATCH_WEIGHT = 1.3  # golden set 2026-10-19: hit@10 unchanged, MRR 0.804 -> 0.817, PF1 result table rank 5 -> 2
MAX_NAMED_DOCUMENTS = 10


def figure_intent(text: str, terms: tuple[str, ...] = DEFAULT_FIGURE_TERMS) -> bool:
    """Whether a question or query asks for content shown in a figure or table."""
    lowered = str(text or "").lower()
    return any(term.lower() in lowered for term in terms)
# Dense retrieval scans every vector instead of walking the HNSW graph: with ~32k chunks it costs ~30 ms, and the
# result no longer depends on the state of a zone's index (DA40 after re-imports: HNSW recall@50 0.78, exact 1.00).
DEFAULT_VECTOR_EXACT = True
_WFA_ID = re.compile(r"(?<!\d)\d{5,6}(?!\d)")


# Scores are compared at this precision: the same chunk scores 24.407490 in one Qdrant and 24.407488 in another
# (float sums in a different segment order), which would otherwise decide the order of equally relevant chunks.
SCORE_DECIMALS = 4
# Extra candidates fetched beyond ``options.candidates`` so that chunks tied at the cut-off are chosen by id here
# rather than by whichever the server happened to return first.
CANDIDATE_MARGIN = 25


def _ranked(points, limit: int | None = None) -> list[str]:
    """Point ids by score; equal scores (frequent in BM25) are ordered by id, so every call and every data zone
    returns them in the same order instead of whatever order the segments happened to yield."""
    ordered = [str(p.id) for p in sorted(points, key=lambda p: (-round(p.score, SCORE_DECIMALS), str(p.id)))]
    return ordered if limit is None else ordered[:limit]


@dataclass(frozen=True)
class SearchOptions:
    top_k: int = 8
    per_document: int = 3
    candidates: int = 50
    include_history: bool = False
    publishers: tuple[str, ...] = ()
    document_roles: tuple[str, ...] = ()
    revision_ids: tuple[str, ...] = ()
    figure_focus: bool | None = None  # None: decided from the query text (figure_intent)
    context: str = ""  # the user's question when ``query`` is the agent's own rewrite; document names in it count too


class SearchUnavailable(RuntimeError):
    pass


class Wifi8Search:
    def __init__(self, store: store_module.Wifi8Store, *, qdrant=None,
                 encoder: Callable[[list[str]], list[list[float]]] | None = None, reranker=None,
                 image_weight: float = 1.0, exact: bool = False, figure_weight: float | None = None,
                 figure_terms: tuple[str, ...] = DEFAULT_FIGURE_TERMS, title_weight: float = DEFAULT_TITLE_MATCH_WEIGHT):
        self.store = store
        self.title_weight = title_weight
        self.image_weight = image_weight
        self.figure_weight = image_weight if figure_weight is None else figure_weight
        self.figure_terms = figure_terms
        self.exact = exact
        self.reranker = reranker  # rerank.Reranker or None
        self.package_id = store.package_id
        self.collection = store.chunks_collection
        self.qdrant = qdrant or store.qdrant
        self.encoder = encoder

    @classmethod
    def for_current(cls, importer, *, qdrant=None, encoder=None, embedding_model: str = "",
                    reranker="environment") -> "Wifi8Search":
        current = importer.current()
        package = importer.current_store(qdrant)
        if not current or package is None or package.qdrant is None:
            raise SearchUnavailable("WiFi 專區尚未匯入資料")
        if current.get("embedding_model") and embedding_model and current["embedding_model"] != embedding_model:
            # Query vectors from another model would silently return unrelated chunks.
            raise SearchUnavailable(f"embedding model mismatch: {embedding_model} != {current['embedding_model']}")
        if reranker == "environment":
            from .rerank import from_environment
            reranker = from_environment()
        image_weight = float(os.getenv("KM_WIFI8_IMAGE_SCORE_WEIGHT", str(DEFAULT_IMAGE_WEIGHT)))
        exact = os.getenv("KM_WIFI8_VECTOR_EXACT", str(DEFAULT_VECTOR_EXACT)).strip().lower() in ("1", "true", "yes", "on")
        figure_weight = float(os.getenv("KM_WIFI8_IMAGE_FOCUS_WEIGHT", str(DEFAULT_FIGURE_FOCUS_WEIGHT)))
        terms = tuple(t.strip() for t in os.getenv("KM_WIFI8_FIGURE_TERMS", "").split(",") if t.strip()) or DEFAULT_FIGURE_TERMS
        title_weight = float(os.getenv("KM_WIFI8_TITLE_MATCH_WEIGHT", str(DEFAULT_TITLE_MATCH_WEIGHT)))
        return cls(package, encoder=encoder, reranker=reranker, image_weight=image_weight, exact=exact,
                   figure_weight=figure_weight, figure_terms=terms, title_weight=title_weight)

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

    def named_documents(self, query: str, documents: dict[str, dict[str, Any]] | None = None) -> dict[str, str]:
        """{revision_id: title} of the documents whose title carries a short name (PF1, EE1 ...) that the query also contains."""
        wanted = text_codes(query)
        if not wanted:
            return {}
        documents = self._documents() if documents is None else documents
        by_code: dict[str, set[str]] = {}
        for revision_id, doc in documents.items():
            if not doc.get("analysis_eligible"):
                continue  # superseded versions share the name; the current one is what a question means
            for code in title_codes(doc.get("title")) & wanted:
                by_code.setdefault(code, set()).add(revision_id)
        ids = set().union(*(ids for ids in by_code.values() if len(ids) <= MAX_NAMED_DOCUMENTS)) if by_code else set()
        return {rid: documents[rid].get("title") or rid for rid in ids}

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
                                          limit=options.candidates + CANDIDATE_MARGIN, with_payload=False)
        return _ranked(result.points, options.candidates)

    def vector(self, query: str, options: SearchOptions) -> list[str]:
        if self.encoder is None:
            return []
        from qdrant_client.models import SearchParams
        result = self.qdrant.query_points(self.collection, query=list(self.encoder([query])[0]), using=store_module.DENSE,
                                          query_filter=self._filter(options), limit=options.candidates + CANDIDATE_MARGIN, with_payload=False,
                                          search_params=SearchParams(exact=self.exact))
        return _ranked(result.points, options.candidates)

    # ---- fusion -------------------------------------------------------
    def search(self, query: str, options: SearchOptions | None = None) -> dict[str, Any]:
        documents = self._documents()
        options = self._resolve(query, options or SearchOptions(), documents)
        lexical = self.lexical(query, options)
        vector = self.vector(query, options)
        scores: dict[str, float] = {}
        for ranking in (lexical, vector):
            for rank, point_id in enumerate(ranking, 1):
                scores[point_id] = scores.get(point_id, 0.0) + 1.0 / (RRF_K + rank)
        chunks = self.chunks(list(scores))
        focus = options.figure_focus if options.figure_focus is not None else figure_intent(query, self.figure_terms)
        weight = self.figure_weight if focus else self.image_weight
        if weight != 1.0:
            for point_id, chunk in chunks.items():
                if chunk.get("image"):
                    scores[point_id] *= weight
        named = self.named_documents(f"{query} {options.context}", documents) if self.title_weight != 1.0 else set()
        for point_id, chunk in chunks.items():
            if chunk["revision_id"] in named:
                scores[point_id] *= self.title_weight
        ordered = sorted(scores, key=lambda pid: (-scores[pid], pid))
        rerank_scores = self._rerank(query, [pid for pid in ordered if pid in chunks], chunks)
        if rerank_scores:
            ordered = sorted(rerank_scores, key=lambda pid: -rerank_scores[pid]) + [pid for pid in ordered if pid not in rerank_scores]
        per_doc: dict[str, int] = {}
        results = []
        for point_id in ordered:
            chunk = chunks.get(point_id)
            if not chunk or per_doc.get(chunk["revision_id"], 0) >= options.per_document:
                continue
            per_doc[chunk["revision_id"]] = per_doc.get(chunk["revision_id"], 0) + 1
            results.append({**chunk, "score": round(scores[point_id], 6),
                            **({"rerank_score": round(rerank_scores[point_id], 4)} if point_id in rerank_scores else {}),
                            "matched_by": [name for name, r in (("fulltext", lexical), ("vector", vector)) if point_id in r]})
            if len(results) >= options.top_k:
                break
        return {"query": query, "package_id": self.package_id, "terms": query_terms(query), "figure_focus": focus,
                "filters": {"publishers": list(options.publishers), "document_roles": list(options.document_roles),
                            "revision_ids": list(options.revision_ids)[:20], "include_history": options.include_history},
                "results": results}

    def _rerank(self, query: str, ordered: list[str], chunks: dict[str, dict[str, Any]]) -> dict[str, float]:
        """Cross-encoder scores for the top fused candidates (title + query-focused excerpt)."""
        if self.reranker is None or not ordered:
            return {}
        settings = self.reranker.settings
        head = ordered[: settings.candidates]
        passages = [f"{chunks[pid].get('source') or ''}\n{excerpt(chunks[pid]['content'], query, settings.chars)[0]}" for pid in head]
        return dict(zip(head, self.reranker.score(query, passages)))

    def chunks(self, point_ids: list[str]) -> dict[str, dict[str, Any]]:
        documents = self._documents()
        result = {}
        for point_id, payload in self.store.chunks(point_ids).items():
            doc = documents.get(payload["revision_id"]) or {}
            result[point_id] = {
                "point_id": point_id, "revision_id": payload["revision_id"], "chunk_index": payload["chunk_index"],
                "source": doc.get("title") or payload.get("doc_name"), "content": payload["content"],
                "display_text": payload.get("display_text"),
                "image": payload.get("image"),
                "location": payload.get("location") or {}, "location_label": payload.get("location_label") or "",
                "segment_ids": payload.get("segment_ids") or [],
                "wfa_document_id": doc.get("wfa_document_id"), "wfa_revision": doc.get("wfa_revision"),
                "document_role": doc.get("document_role"), "publisher": doc.get("publisher"),
                "analysis_eligible": bool(doc.get("analysis_eligible")), "document_date": doc.get("document_date"),
                "storage_category": "WiFi", "source_system": "WIFI8",
            }
        return result
