"""The documents CSIT delivered to one knowledge zone, read back from the vector collections they were written to.

A zone page shows documents, versions and passages. KM keeps them as points (one per passage) tagged with the zone KM decided for the document
(topic_zone, see csit_integration_v1/zones.py); this module groups the points of a zone into documents and searches their passages.
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable

# (collection, named vector or None, payload key of the passage text, extra must conditions)
SOURCES = (
    ("km_csit_docs", None, "content", ()),
    ("knowledge_base", None, "content", ()),
    ("ai_km_knowledge_v1", "dense", "chunk_text", (("source_system", "CSIT"),)),   # shared with legacy documents: only CSIT's points
)
TYPE_ZH = {"Specification": "規格文件", "Manual": "手冊", "TestReport": "測試報告", "SOP": "作業程序", "MeetingMinutes": "會議紀錄", "IssueAnalysis": "問題分析",
           "Presentation": "簡報", "Other": "其他"}
TYPE_DESCRIPTION = {"規格文件": "技術規格與標準", "手冊": "操作與使用手冊", "測試報告": "測試結果與判定", "作業程序": "標準作業流程", "會議紀錄": "會議與討論紀錄",
                    "問題分析": "問題與根因分析", "簡報": "簡報與講義", "其他": "其他文件"}
SOURCE_ZH = {"DocumentLibraryFile": "文件庫", "VerificationApplicationAttachment": "驗證申請附件", "VendorFile": "廠商檔案", "EquipmentAttachment": "設備附件",
             "TestReport": "測試報告（CSIT）"}
UNCLASSIFIED = "待分類"
PAGE = 256
CANDIDATES = 40
MAX_SUBJECTS = 4
PER_SUBJECT = 3
STOPWORDS = {"the", "and", "or", "vs", "of", "in", "to", "is", "are", "what", "which", "how", "for", "with", "on", "a", "an", "pass", "fail", "test", "report"}


def _date(value: Any) -> str | None:
    return str(value)[:10] if value else None


def identity(collection: str, p: dict[str, Any]) -> dict[str, Any]:
    """Who a point belongs to: the document's revision id, its family (the same document across versions), a version label and the payload fields that select
    exactly this document again."""
    if collection == "ai_km_knowledge_v1":                     # report templates: the CSIT id is in source_record_id ("<documentId>:v<version>")
        rid = str(p.get("source_record_id") or f"{p.get('document_id')}:{p.get('document_version')}")
        family = rid.rsplit(":v", 1)[0]
        return {"revision_id": rid, "family": family, "version_label": str(p.get("document_version") or ""), "source_type": "TestReport",
                "title": p.get("title") or p.get("document_id"), "match": [("source_record_id", p.get("source_record_id"))] if p.get("source_record_id") else
                [("document_id", p.get("document_id")), ("document_version", p.get("document_version"))]}
    if collection == "knowledge_base":                          # Test Report v1 (generic path)
        doc, ver = p.get("document_id"), p.get("document_version")
        return {"revision_id": f"{doc}:v{ver}", "family": str(doc), "version_label": f"v{ver}", "source_type": "TestReport", "title": p.get("doc_name") or str(doc),
                "match": [("document_id", doc), ("document_version", ver)]}
    if p.get("source_entity_id"):                               # v1.4 sources
        doc, ver = p.get("document_id"), p.get("document_version")
        return {"revision_id": f"{doc}:v{ver}", "family": str(p["source_entity_id"]), "version_label": f"v{ver}", "source_type": p.get("source_type"),
                "title": p.get("doc_name") or str(doc), "match": [("source_entity_id", p["source_entity_id"]), ("document_id", doc), ("document_version", ver)]}
    fid = str(p.get("document_file_id"))                         # v1.3 library file
    return {"revision_id": fid, "family": fid, "version_label": "v1", "source_type": p.get("source_type") or "DocumentLibraryFile", "title": p.get("doc_name") or fid,
            "match": [("document_file_id", fid)]}


def _zone_filter(zone_names: list[str], extra=(), must_not_superseded=False):
    from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
    must = [FieldCondition(key="topic_zone", match=MatchAny(any=list(zone_names))), *[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in extra]]
    return Filter(must=must, must_not=[FieldCondition(key="index_state", match=MatchValue(value="Superseded"))] if must_not_superseded else None)


class ZoneCatalog:
    def __init__(self, client, encode: Callable, sources=SOURCES, ttl: float = 15.0, clock: Callable[[], float] = time.monotonic):
        self.client, self.encode, self.sources, self.ttl, self.clock = client, encode, sources, ttl, clock
        self._cache: dict[tuple, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()

    # ---------- documents ----------
    def _points(self, collection: str, flt):
        offset = None
        while True:
            try:
                points, offset = self.client.scroll(collection, scroll_filter=flt, limit=PAGE, offset=offset, with_payload=True, with_vectors=False)
            except Exception:                                   # a collection that does not exist yet: nothing delivered into it so far
                return
            yield from points
            if offset is None:
                return

    def documents(self, zone_names: list[str], fresh: bool = False) -> list[dict]:
        key = tuple(zone_names)
        with self._lock:
            hit = self._cache.get(key)
            if hit and not fresh and self.clock() - hit[0] < self.ttl:
                return hit[1]
        docs: dict[str, dict] = {}
        for collection, _using, text_key, extra in self.sources:
            for point in self._points(collection, _zone_filter(zone_names, extra)):
                p = point.payload or {}
                ident = identity(collection, p)
                d = docs.get(ident["revision_id"])
                if d is None:
                    d = docs[ident["revision_id"]] = {
                        "revision_id": ident["revision_id"], "family": ident["family"], "version_label": ident["version_label"], "source_type": ident["source_type"],
                        "title": ident["title"], "publisher": SOURCE_ZH.get(ident["source_type"], str(ident["source_type"] or "")),
                        "document_type": p.get("document_type") or ("TestReport" if ident["source_type"] == "TestReport" else None), "summary": p.get("summary"),
                        "keywords": list(p.get("keywords") or []), "indexed_at": p.get("indexed_at"), "superseded_at": p.get("superseded_at"),
                        "analysis_eligible": p.get("index_state") != "Superseded", "topic_zone": p.get("topic_zone"), "zone_basis": p.get("zone_basis"),
                        "classification": p.get("classification") or {}, "chunks": 0, "_collection": collection, "_match": ident["match"]}
                d["chunks"] += 1
                for field in ("summary", "indexed_at", "document_type", "superseded_at"):   # the first point may predate a later one that carries the field
                    if not d.get(field) and p.get(field):
                        d[field] = p[field]
                if not d["keywords"] and p.get("keywords"):
                    d["keywords"] = list(p["keywords"])
        out = []
        for d in docs.values():
            d["document_role"] = TYPE_ZH.get(d["document_type"], "其他") if d["document_type"] else "其他"
            d["document_date"] = _date(d["indexed_at"])
            if d["topic_zone"] == UNCLASSIFIED:
                d["document_role"] = UNCLASSIFIED + "（待確認）"
            out.append(d)
        out.sort(key=lambda d: (d["document_date"] or "", d["title"] or ""), reverse=True)
        with self._lock:
            self._cache[key] = (self.clock(), out)
        return out

    def document(self, zone_names: list[str], revision_id: str) -> dict | None:
        return next((d for d in self.documents(zone_names) if d["revision_id"] == revision_id), None)

    def versions(self, zone_names: list[str], doc: dict) -> list[dict]:
        return sorted((d for d in self.documents(zone_names) if d["family"] == doc["family"]), key=lambda d: d["document_date"] or "", reverse=True)

    def chunks(self, doc: dict, count: int = 8) -> tuple[list[dict], int]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue
        flt = Filter(must=[FieldCondition(key=k, match=MatchValue(value=v)) for k, v in doc["_match"]])
        text_key = next(t for c, _u, t, _e in self.sources if c == doc["_collection"])
        rows = [{"chunk_index": (p.payload or {}).get("chunk_index") or 0, "location_label": location(doc["_collection"], p.payload or {}), "content": (p.payload or {}).get(text_key) or ""}
                for p in self._points(doc["_collection"], flt)]
        rows.sort(key=lambda r: r["chunk_index"])
        return rows[:count], len(rows)

    # ---------- search ----------
    def search(self, query: str, zone_names: list[str], top_k: int = 10, include_history: bool = False) -> list[dict]:
        docs = {d["revision_id"]: d for d in self.documents(zone_names)}
        vector = list(map(float, self.encode([query])[0]))
        hits = []
        for collection, using, text_key, extra in self.sources:
            try:
                points = self.client.query_points(collection, query=vector, using=using, query_filter=_zone_filter(zone_names, extra, not include_history),
                                                  limit=CANDIDATES, with_payload=True).points
            except Exception:
                continue
            for point in points:
                p = point.payload or {}
                doc = docs.get(identity(collection, p)["revision_id"])
                if doc is not None:
                    hits.append({"score": float(getattr(point, "score", 0) or 0), "doc": doc, "chunk": {
                        "chunk_index": p.get("chunk_index") or 0, "location_label": location(collection, p), "content": p.get(text_key) or ""}})
        hits.sort(key=lambda h: h["score"], reverse=True)
        return spread(hits, query, top_k)


def subjects(query: str, hits: list[dict]) -> list[str]:
    """The names (NG, Xn, SCU2050 ...) the question mentions that some candidate passage also mentions, in the order asked."""
    out = []
    for word in re.findall(r"[A-Za-z][A-Za-z0-9]+", query):
        low = word.lower()
        if low in STOPWORDS or low in out:
            continue
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(low) + r"(?![A-Za-z0-9])")
        if any(pattern.search(h["chunk"]["content"].lower()) for h in hits):
            out.append(low)
    return out[:MAX_SUBJECTS]


def spread(hits: list[dict], query: str, top_k: int) -> list[dict]:
    """The best passages, but at least PER_SUBJECT for each name the question mentions: a question comparing NG with Xn must reach both, even when
    the passages of one are the closer match for every word of the question."""
    chosen = hits[:top_k]
    names = subjects(query, hits)
    if len(names) < 2:
        return chosen
    has = lambda h, n: re.search(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", h["chunk"]["content"].lower()) is not None
    for n in names:
        missing = PER_SUBJECT - sum(1 for h in chosen if has(h, n))
        if missing <= 0:
            continue
        extra = [h for h in hits[top_k:] if has(h, n)][:missing]
        for add in extra:
            # make room by dropping the lowest-ranked passage that no subject needs
            drop = next((h for h in reversed(chosen) if not any(has(h, m) and sum(1 for c in chosen if has(c, m)) <= PER_SUBJECT for m in names)), None)
            if drop is None:
                return chosen
            chosen.remove(drop)
            chosen.append(add)
    chosen.sort(key=lambda h: h["score"], reverse=True)
    return chosen


def location(collection: str, p: dict[str, Any]) -> str:
    if collection == "ai_km_knowledge_v1" and p.get("source_sheet"):
        return f"{p['source_sheet']}{'・' + str(p['source_cell_range']) if p.get('source_cell_range') else ''}"
    return f"第 {int(p.get('chunk_index') or 0) + 1} 段"
