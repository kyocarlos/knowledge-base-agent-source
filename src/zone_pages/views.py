"""The JSON the zone pages read, built from the zone's documents (the same shapes the pages were written against: /api/wifi8/overview, /documents, /search, /feed)."""
from __future__ import annotations

import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from .catalog import TYPE_DESCRIPTION, UNCLASSIFIED

RECENT = 8


def doc_view(d: dict) -> dict[str, Any]:
    return {"revision_id": d["revision_id"], "wfa_document_id": d["revision_id"].split(":")[0][:8].upper(), "title": d["title"], "publisher": d["publisher"],
            "document_role": d["document_role"], "document_date": d["document_date"], "version_label": d["version_label"], "analysis_eligible": d["analysis_eligible"],
            "summary": d.get("summary"), "keywords": d.get("keywords") or [], "chunks": d["chunks"], "zone_basis": d.get("zone_basis")}


def _tally(items: list[str]) -> list[list]:
    return [[k, v] for k, v in Counter(items).most_common()]


def overview(docs: list[dict], zone_label: str) -> dict[str, Any]:
    current = [d for d in docs if d["analysis_eligible"]]
    chunks = sum(d["chunks"] for d in docs)
    rows = []
    for role, n in Counter(d["document_role"] for d in docs).most_common():
        mine = [d for d in docs if d["document_role"] == role]
        cur = sum(1 for d in mine if d["analysis_eligible"])
        rows.append({"label": role, "description": TYPE_DESCRIPTION.get(role, "依內容判斷"), "total": n, "current": cur, "history": n - cur, "share": n / len(docs) * 100 if docs else 0})
    unclassified = [d for d in current if d["topic_zone"] == UNCLASSIFIED]
    attention = ([{"level": "warning", "title": f"{len(unclassified)} 份文件待分類", "detail": "KM 讀完內容仍無法判斷專區，先放在這裡，請人工確認後再歸類"}] if unclassified else [])
    keywords = Counter(k for d in current for k in d.get("keywords") or [])

    def coverage(label, present):
        return {"label": label, "total": len(docs), "present": present}
    return {
        "counts": {"documents": len(docs), "current_documents": len(current), "superseded_documents": len(docs) - len(current), "chunks": chunks, "chunks_ready": chunks,
                   "chunks_pending": 0, "excluded": {}},
        "current": {"package_id": zone_label}, "active_job": None, "qna_documents": len(current), "attention": attention,
        "by_category": {"total": len(docs), "rows": rows}, "by_publisher": _tally([d["publisher"] for d in current]),
        "by_document_role": _tally([d["document_role"] for d in current]), "top_topics": [[k, n] for k, n in keywords.most_common(8)],
        "processing": {"text_status": [["indexed", len(docs)]], "failed_jobs": 0, "latest_failure": None,
                       "metadata_coverage": [coverage("文件類型", sum(1 for d in docs if d["document_type"])), coverage("摘要", sum(1 for d in docs if d.get("summary"))),
                                             coverage("關鍵字", sum(1 for d in docs if d.get("keywords"))), coverage("更新日期", sum(1 for d in docs if d["document_date"]))]},
    }


def _match(d: dict, query: str) -> bool:
    haystack = " ".join([d["title"] or "", d.get("summary") or "", " ".join(d.get("keywords") or []), d["publisher"], d["document_role"]]).lower()
    return all(term in haystack for term in query.lower().split())


def list_documents(docs: list[dict], *, query: str = "", publisher: str | None = None, role: str | None = None, history: bool = False, page: int = 1, size: int = 20) -> dict:
    pool = docs if history else [d for d in docs if d["analysis_eligible"]]
    facets = {"publishers": _tally([d["publisher"] for d in pool]), "document_roles": _tally([d["document_role"] for d in pool])}
    if publisher:
        pool = [d for d in pool if d["publisher"] == publisher]
    if role:
        pool = [d for d in pool if d["document_role"] == role]
    if query.strip():
        pool = [d for d in pool if _match(d, query)]
    size, page = max(1, min(size, 100)), max(1, page)
    return {"total": len(pool), "page": page, "page_size": size, "documents": [doc_view(d) for d in pool[(page - 1) * size:page * size]], "facets": facets}


def search_result(hit: dict) -> dict:
    d, c = hit["doc"], hit["chunk"]
    return {**doc_view(d), "source": d["title"], "content": c["content"], "location_label": c["location_label"], "chunk_index": c["chunk_index"], "matched_by": ["vector"],
            "score": round(hit["score"], 4)}


def _iso_week(when: datetime) -> str:
    y, w, _ = when.isocalendar()
    return f"{y}-W{w:02d}"


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def events(docs: list[dict], limit: int = 30) -> list[dict]:
    out = []
    for d in docs:
        stamp = d["indexed_at"]
        if stamp:
            out.append({"type": "new_document", "at": stamp, "title": d["title"], "publisher": d["publisher"], "document_role": d["document_role"],
                        "version_label": d["version_label"], "revision_id": d["revision_id"]})
        if not d["analysis_eligible"] and d.get("superseded_at"):
            out.append({"type": "superseded", "at": d["superseded_at"], "title": d["title"], "publisher": d["publisher"], "document_role": d["document_role"],
                        "version_label": d["version_label"], "revision_id": d["revision_id"]})
    out.sort(key=lambda e: str(e["at"]), reverse=True)
    return out[:limit]


def week_items(docs: list[dict], now: datetime | None = None, days: int = 7) -> list[dict]:
    """The documents delivered in the last week, newest first: the raw material of the weekly digest."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = []
    for d in docs:
        when = _parse(d["indexed_at"])
        if when and when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when and when >= since and d["analysis_eligible"]:
            rows.append({"source_name": d["publisher"], "published": d["indexed_at"], "title": d["title"], "summary": d.get("summary") or "", "role": d["document_role"],
                         "revision_id": d["revision_id"]})
    rows.sort(key=lambda r: str(r["published"]), reverse=True)
    return rows


def feed(docs: list[dict], digest: dict[str, Any]) -> dict[str, Any]:
    current = [d for d in docs if d["analysis_eligible"]]
    recent = [doc_view(d) for d in current[:RECENT]]
    return {"digest": digest, "updates": {"events": events(docs), "recent": recent}}


def digest_shell(docs: list[dict], highlights: list[str], note: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    items = week_items(docs, now)
    return {"week": _iso_week(now), "generated_at": now.isoformat(), "highlights": highlights, "timeline": None,
            "items": [{"source_name": i["source_name"], "published": i["published"], "title": i["title"], "summary": i["summary"]} for i in items],
            "sources": [{"name": n, "status": "ok"} for n in sorted({i["source_name"] for i in items})], "note": note}
