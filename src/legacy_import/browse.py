"""Reading imported legacy documents back: topic-zone search and Q&A (Qdrant) and the zone / category / document lists (Neo4j).

Legacy points (origin = legacy_nas) are read from the shared collection; the Wi-Fi zone's own collections are untouched. Documents CSIT delivered carry the
zone KM decided for them (topic_zone) and are read from the collections they were written to (CSIT_SOURCES), only when the caller names the zone's
topic_zone values (csit_zones). The sensitive-document rule is applied at import time: those files are not in any store.
"""
from __future__ import annotations

from typing import Callable

COLLECTION = "ai_km_knowledge_v1"
DENSE, SPARSE = "dense", "text"
ORIGIN = "legacy_nas"
# Where documents delivered by CSIT live: (collection, named vector or None, payload key of the passage text, extra must conditions).
# Test Reports of the registered templates share ai_km_knowledge_v1 with the legacy documents, so only their CSIT points are taken from it.
CSIT_SOURCES = (("km_csit_docs", None, "content", ()), ("knowledge_base", None, "content", ()), ("ai_km_knowledge_v1", DENSE, "chunk_text", (("source_system", "CSIT"),)))
RRF_K = 60
CANDIDATES = 60
CONTEXT_PASSAGES = 8
MAX_PASSAGE_CHARS = 700

ANSWER_SYSTEM = """你是企業知識庫的助理。只能根據下列「資料」回答，不可使用資料以外的知識或推測。
- 資料中找不到答案時，直接說「在這個專區的資料裡找不到相關內容」，並說明資料裡有什麼相近的內容（若有）。
- 回答使用與問題相同的語言，條列重點，每個重點後面用 [S1]、[S2] 標示資料來源編號。
- 不要編造型號、版本、日期、數值。"""


def _conditions(zone: str | None, l1: str | None, l2: str | None, l3: str | None, document_type: str | None, document_id: str | None):
    from qdrant_client.models import FieldCondition, MatchValue
    conditions = [FieldCondition(key="origin", match=MatchValue(value=ORIGIN))]
    for key, value in (("topic_zone", zone), ("l1", l1), ("l2", l2), ("l3", l3), ("document_type", document_type), ("document_id", document_id)):
        if value:
            conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))
    return conditions


def qdrant_filter(zone=None, l1=None, l2=None, l3=None, document_type=None, document_id=None):
    from qdrant_client.models import Filter
    return Filter(must=_conditions(zone, l1, l2, l3, document_type, document_id))


class ZoneSearch:
    """Hybrid (dense + keyword) retrieval inside one topic zone, merged with reciprocal-rank fusion and grouped by document."""

    def __init__(self, client, encode: Callable, query_sparse: Callable, csit_sources=CSIT_SOURCES):
        self.client, self.encode, self.query_sparse = client, encode, query_sparse
        self.csit_sources = csit_sources

    def _csit_documents(self, query: str, csit_zones: list[str]) -> list[dict]:
        """Dense retrieval over the collections CSIT documents were written to, restricted to the zone; one document per hit, best passage first.
        A collection that does not exist yet (nothing delivered so far) contributes nothing."""
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
        vector = list(map(float, self.encode([query])[0]))
        documents: dict[tuple, dict] = {}
        for collection, using, text_key, extra in self.csit_sources:
            flt = Filter(must=[FieldCondition(key="topic_zone", match=MatchAny(any=csit_zones)), *[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in extra]],
                         must_not=[FieldCondition(key="index_state", match=MatchValue(value="Superseded"))])
            try:
                points = self.client.query_points(collection, query=vector, using=using, query_filter=flt, limit=CANDIDATES, with_payload=True).points
            except Exception:
                continue
            for point in points:
                p = point.payload or {}
                doc_id = p.get("document_file_id") or p.get("document_id")
                name = p.get("doc_name") or p.get("title") or doc_id
                cls = p.get("classification") or {}
                doc = documents.setdefault((collection, doc_id), {
                    "document_id": doc_id, "title": name, "source_paths": [name], "topic_zone": p.get("topic_zone"), "l1": cls.get("l1"), "l2": cls.get("l2"),
                    "l3": cls.get("l3"), "document_type": p.get("document_type") or p.get("source_type"), "document_date": None, "needs_review": p.get("zone_basis") == "none",
                    "origin": "csit", "passages": []})
                doc["passages"].append({"chunk_index": p.get("chunk_index"), "text": p.get(text_key) or ""})
        return list(documents.values())

    def _ranked(self, query: str, flt) -> list:
        from qdrant_client.models import SparseVector
        lists = []
        dense = self.client.query_points(COLLECTION, query=list(map(float, self.encode([query])[0])), using=DENSE, query_filter=flt,
                                         limit=CANDIDATES, with_payload=True)
        lists.append(dense.points)
        idx, vals = self.query_sparse(query)
        if idx:
            lexical = self.client.query_points(COLLECTION, query=SparseVector(indices=idx, values=vals), using=SPARSE, query_filter=flt,
                                               limit=CANDIDATES, with_payload=True)
            lists.append(lexical.points)
        scores: dict = {}
        points: dict = {}
        for points_list in lists:
            for rank, point in enumerate(points_list):
                scores[point.id] = scores.get(point.id, 0.0) + 1.0 / (RRF_K + rank + 1)
                points[point.id] = point
        return [(scores[pid], points[pid]) for pid in sorted(scores, key=scores.get, reverse=True)]

    def search(self, query: str, *, zone=None, l1=None, l2=None, l3=None, document_type=None, top_k: int = 10, csit_zones=None) -> list[dict]:
        hits = self._legacy_search(query, zone=zone, l1=l1, l2=l2, l3=l3, document_type=document_type, top_k=top_k)
        if not csit_zones or l1 or l2 or l3 or document_type:   # the category filters are the legacy taxonomy's; CSIT documents have none of it
            return hits
        theirs = self._csit_documents(query.strip(), list(csit_zones))
        if not theirs:
            return hits
        # Two independent retrievers with different score scales: merge by rank (reciprocal-rank fusion), as the dense and keyword lists already are.
        fused: dict[int, float] = {}
        merged = hits + theirs
        for group in (hits, theirs):
            for rank, doc in enumerate(group):
                fused[id(doc)] = 1.0 / (RRF_K + rank + 1)
        return [doc for doc in sorted(merged, key=lambda d: fused[id(d)], reverse=True)][:top_k]

    def _legacy_search(self, query: str, *, zone=None, l1=None, l2=None, l3=None, document_type=None, top_k: int = 10) -> list[dict]:
        ranked = self._ranked(query.strip(), qdrant_filter(zone, l1, l2, l3, document_type))
        documents: dict[str, dict] = {}
        for score, point in ranked:
            p = point.payload or {}
            doc = documents.setdefault(p.get("document_id"), {
                "document_id": p.get("document_id"), "title": p.get("title"), "source_paths": p.get("source_paths") or [], "topic_zone": p.get("topic_zone"),
                "l1": p.get("l1"), "l2": p.get("l2"), "l3": p.get("l3"), "document_type": p.get("document_type"), "document_date": p.get("document_date"),
                "needs_review": bool(p.get("needs_review")), "score": score, "passages": []})
            doc["passages"].append({"chunk_index": p.get("chunk_index"), "text": p.get("chunk_text") or ""})
        return list(documents.values())[:top_k]

    def document_chunks(self, document_id: str, limit: int = 400) -> list[dict]:
        points, _ = self.client.scroll(COLLECTION, scroll_filter=qdrant_filter(document_id=document_id), limit=limit, with_payload=True, with_vectors=False)
        return sorted(({"chunk_index": (p.payload or {}).get("chunk_index"), "text": (p.payload or {}).get("chunk_text") or ""} for p in points),
                      key=lambda c: c["chunk_index"] or 0)


def build_sources(hits: list[dict], max_passages: int = CONTEXT_PASSAGES) -> tuple[list[dict], list[dict]]:
    """Numbered passages for the prompt (S1, S2, ...) and the citation list returned to the page."""
    passages, citations = [], []
    for hit in hits:
        for passage in hit["passages"][:2]:
            if len(passages) >= max_passages:
                break
            ref = f"S{len(passages) + 1}"
            text = passage["text"][:MAX_PASSAGE_CHARS]
            passages.append({"ref": ref, "text": text, "title": hit["title"], "path": (hit["source_paths"] or [""])[0]})
            citations.append({"ref": ref, "document_id": hit["document_id"], "title": hit["title"], "source_path": (hit["source_paths"] or [""])[0],
                              "topic_zone": hit["topic_zone"], "category": " / ".join(x for x in (hit["l1"], hit["l2"], hit["l3"]) if x), "excerpt": text[:240]})
    return passages, citations


def answer(complete: Callable[[list[dict]], str], question: str, hits: list[dict]) -> dict:
    """Grounded answer over the retrieved passages. With no passages the model is not called."""
    passages, citations = build_sources(hits)
    if not passages:
        return {"answer": "在這個專區的資料裡找不到相關內容。", "citations": [], "grounded": False}
    context = "\n\n".join(f"[{p['ref']}] {p['title']}（{p['path']}）\n{p['text']}" for p in passages)
    reply = complete([{"role": "system", "content": ANSWER_SYSTEM}, {"role": "user", "content": f"資料：\n{context}\n\n問題：{question}"}])
    return {"answer": reply.strip(), "citations": citations, "grounded": True}


class ZoneCatalogue:
    """Zone, category and document lists from the Neo4j Legacy* graph."""

    def __init__(self, driver, database: str | None = None):
        self.driver, self.database = driver, database

    def _run(self, query: str, **params) -> list[dict]:
        session = self.driver.session(database=self.database) if self.database else self.driver.session()
        with session:
            return [record.data() for record in session.run(query, **params)]

    def zones(self) -> list[dict]:
        return self._run("MATCH (d:LegacyDocument) RETURN d.topic_zone AS zone, count(d) AS documents, "
                         "sum(CASE WHEN d.needs_review THEN 1 ELSE 0 END) AS needs_review ORDER BY zone")

    def categories(self, zone: str) -> list[dict]:
        return self._run("MATCH (d:LegacyDocument {topic_zone: $zone})-[:CLASSIFIED_AS]->(c:LegacyCategory) "
                         "RETURN c.l1 AS l1, c.l2 AS l2, c.l3 AS l3, count(d) AS documents ORDER BY l1, l2, l3", zone=zone)

    def documents(self, zone: str, *, l1=None, l2=None, l3=None, text: str | None = None, skip: int = 0, limit: int = 50) -> dict:
        where = ["d.topic_zone = $zone"]
        match = "MATCH (d:LegacyDocument)"
        if l1 or l2 or l3:
            match = "MATCH (d:LegacyDocument)-[:CLASSIFIED_AS]->(c:LegacyCategory)"
            for name, value in (("l1", l1), ("l2", l2), ("l3", l3)):
                if value:
                    where.append(f"c.{name} = ${name}")
        if text:
            where.append("(toLower(d.title) CONTAINS toLower($text) OR any(p IN d.source_paths WHERE toLower(p) CONTAINS toLower($text)))")
        params = {"zone": zone, "l1": l1, "l2": l2, "l3": l3, "text": text, "skip": max(0, skip), "limit": max(1, min(limit, 200))}
        clause = f"{match} WHERE {' AND '.join(where)}"
        total = self._run(f"{clause} RETURN count(d) AS n", **params)[0]["n"]
        items = self._run(f"{clause} RETURN d.document_id AS document_id, d.title AS title, d.document_type AS document_type, d.summary AS summary, "
                          "d.document_date AS document_date, d.source_paths AS source_paths, d.needs_review AS needs_review, "
                          "d.classification_confidence AS confidence ORDER BY d.title SKIP $skip LIMIT $limit", **params)
        return {"total": total, "items": items}

    def document(self, document_id: str) -> dict | None:
        rows = self._run("MATCH (d:LegacyDocument {document_id: $id}) OPTIONAL MATCH (d)-[:CLASSIFIED_AS]->(c:LegacyCategory) "
                         "OPTIONAL MATCH (d)-[:MENTIONS]->(e:LegacyEntity) "
                         "RETURN d{.document_id, .title, .document_type, .summary, .document_date, .source_paths, .topic_zone, .needs_review, "
                         ".classification_confidence, .language, .keywords, .import_batch} AS doc, c.l1 AS l1, c.l2 AS l2, c.l3 AS l3, "
                         "collect(DISTINCT {kind: e.kind, name: e.name}) AS entities", id=document_id)
        if not rows:
            return None
        row = rows[0]
        return {**row["doc"], "l1": row["l1"], "l2": row["l2"], "l3": row["l3"], "entities": [e for e in row["entities"] if e.get("name")]}
