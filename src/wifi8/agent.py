"""WiFi zone agent: a tool-using loop over read-only WiFi knowledge tools.

The model decides which tool to call; tools, step limits, time budget and the
citation registry are ordinary code. The model never receives database access,
free-form queries or file paths -- only the fixed tools below.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from .excerpt import excerpt, table_excerpt
from .quality import QUALITY_LOG_PREFIX
from .search import SearchOptions, Wifi8Search

SYSTEM_PROMPT = """你是 KM「WiFi 知識專區」的研究助理，可查詢已匯入的 Wi-Fi 文件（WFA 規格與 MRD、測試計畫與測項、晶片廠商資料、研究論文、產業報告等）。
規則：
1. 只能根據工具回傳的內容回答；先用工具查證，再作答。資料不足時明確說明缺什麼，不要推測或補造數值、版本、日期。
2. 引用時在句末標註來源編號，例如 [S3]；只能使用工具回傳過的編號。
3. 預設只採用目前有效版本；使用者問歷史、版本差異或指定舊版時，才用 include_history 或 list_versions。
4. WFA proprietary 文件只摘要必要結論，不要大量逐字引用。
5. 以繁體中文回答；技術名詞、文件名稱、識別碼保持原文。回答先給結論，再列重點與依據。"""

TOOLS = [
    {"type": "function", "function": {
        "name": "search_wifi",
        "description": "混合檢索 WiFi 專區（全文＋語意）。回傳段落與來源編號；段落過長時只回傳與查詢最相關的句子（excerpt=true，略過處以「…」標示），需要完整內容時用 read_document。預設只查目前有效版本。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "檢索字詞；技術名詞建議用英文原文，例如 ELR、NPCA、MLO"},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 12},
            "include_history": {"type": "boolean", "description": "是否包含已被取代的舊版本"},
            "publisher": {"type": "string", "description": "限定發布者，例如 WFA、Broadcom、Qualcomm"},
            "document_role": {"type": "string", "description": "限定文件角色，例如 MRD、Certification Test Case"},
        }, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_document",
        "description": "取得單一文件的資料：標題、角色、發布者、日期、WFA 文件 ID／版本、是否為目前版本、主題、取代關係。",
        "parameters": {"type": "object", "properties": {
            "revision_id": {"type": "string"}, "wfa_document_id": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "list_versions",
        "description": "列出某文件同一系列的所有版本與新舊取代關係。",
        "parameters": {"type": "object", "properties": {"revision_id": {"type": "string"}}, "required": ["revision_id"]}}},
    {"type": "function", "function": {
        "name": "read_document",
        "description": "依序讀取某文件的段落內容（可指定從第幾個段落開始），用於查看搜尋結果的前後文或完整章節。段落過長時會截取（excerpt=true）；提供 query 可優先保留含這些關鍵詞的句子。",
        "parameters": {"type": "object", "properties": {
            "revision_id": {"type": "string"}, "start": {"type": "integer", "minimum": 1},
            "count": {"type": "integer", "minimum": 1, "maximum": 8},
            "query": {"type": "string", "description": "可選：要聚焦的關鍵詞，例如 WPA3-Enterprise、mandatory"}}, "required": ["revision_id"]}}},
    {"type": "function", "function": {
        "name": "list_documents",
        "description": "依條件列出文件清單（不含內文）：關鍵字（比對標題與主題）、發布者、文件角色。",
        "parameters": {"type": "object", "properties": {
            "keyword": {"type": "string"}, "publisher": {"type": "string"}, "document_role": {"type": "string"},
            "include_history": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}}}}},
    {"type": "function", "function": {
        "name": "zone_overview",
        "description": "WiFi 專區總覽：文件數、各發布者與文件角色的數量、主要主題、匯入版本。",
        "parameters": {"type": "object", "properties": {}}}},
]


def _text_fields(item: dict[str, Any], query: str, limit: int) -> dict[str, Any]:
    """Text shown to the model: tables as Markdown (header always kept), other chunks as query-focused excerpts."""
    text = item.get("content") or ""
    if item.get("display_text"):
        body, cut = table_excerpt(item["display_text"], query, limit)
    else:
        body, cut = excerpt(text, query, limit)
    return {"text": body, "excerpt": True, "chars": len(text)} if cut else {"text": body}


@dataclass(frozen=True)
class AgentSettings:
    max_steps: int = 6
    time_budget_seconds: float = 90.0
    snippet_chars: int = 1000
    read_chars: int = 3000
    grounding: bool = True

    @classmethod
    def from_environment(cls) -> "AgentSettings":
        import os
        return cls(max_steps=int(os.getenv("KM_WIFI8_AGENT_MAX_STEPS", "6")),
                   time_budget_seconds=float(os.getenv("KM_WIFI8_AGENT_TIME_BUDGET_SECONDS", "90")),
                   snippet_chars=int(os.getenv("KM_WIFI8_AGENT_SNIPPET_CHARS", "1000")),
                   read_chars=int(os.getenv("KM_WIFI8_AGENT_READ_CHARS", "3000")),
                   grounding=os.getenv("KM_WIFI8_AGENT_GROUNDING", "1").strip().lower() not in {"0", "false", "no", "off"})


class CitationRegistry:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.texts: dict[str, str] = {}  # full chunk text per ref, for the grounding check only
        self._by_key: dict[str, str] = {}

    def add(self, item: dict[str, Any]) -> str:
        key = item.get("point_id") or f"{item['revision_id']}#{item.get('chunk_index')}"
        if key not in self._by_key:
            ref = f"S{len(self._by_key) + 1}"
            self._by_key[key] = ref
            self.items[ref] = {
                "ref": ref, "source": item.get("source"), "revision_id": item.get("revision_id"), "point_id": item.get("point_id"),
                "location_label": item.get("location_label"), "wfa_document_id": item.get("wfa_document_id"),
                "wfa_revision": item.get("wfa_revision"), "document_role": item.get("document_role"),
                "publisher": item.get("publisher"), "document_date": item.get("document_date"),
                "analysis_eligible": item.get("analysis_eligible"), "content": (item.get("content") or "")[:1200],
                # A chunk made from a figure: the answer page shows the image next to the citation.
                **({"image": item["image"]} if item.get("image") else {}),
                "storage_category": "WiFi", "source_system": "WIFI8",
            }
            self.texts[ref] = item.get("content") or ""
        return self._by_key[key]

    def grounding_sources(self) -> dict[str, dict[str, Any]]:
        return {ref: {**item, "text": self.texts.get(ref, "")} for ref, item in self.items.items()}


class WifiTools:
    def __init__(self, search: Wifi8Search, settings: AgentSettings, citations: CitationRegistry):
        self.search_engine = search
        self.settings = settings
        self.citations = citations
        self.store = search.store
        self.evidence: list[str] = []  # every tool result of the run, for the grounding check

    def _doc_rows(self, **equals: str) -> list[dict[str, Any]]:
        return [d for d in self.store.documents() if all(str(d.get(k) or "") == v for k, v in equals.items())]

    @staticmethod
    def _summary(doc: dict[str, Any]) -> dict[str, Any]:
        keys = ("revision_id", "title", "document_role", "publisher", "document_date", "wfa_document_id", "wfa_revision",
                "version_label", "analysis_eligible", "replacement_id", "topics", "supersedes", "segment_count")
        return {k: doc.get(k) for k in keys if doc.get(k) not in (None, "", [])}

    def search_wifi(self, query: str, top_k: int = 6, include_history: bool = False, publisher: str = "", document_role: str = ""):
        options = SearchOptions(top_k=max(1, min(int(top_k or 6), 12)), include_history=bool(include_history),
                                publishers=(publisher,) if publisher else (), document_roles=(document_role,) if document_role else ())
        result = self.search_engine.search(query, options)
        hits = []
        for item in result["results"]:
            ref = self.citations.add(item)
            hits.append({"ref": ref, "title": item["source"], "revision_id": item["revision_id"], "location": item["location_label"],
                         "chunk_index": item["chunk_index"], "current_version": item["analysis_eligible"],
                         "wfa_document_id": item.get("wfa_document_id"), "publisher": item.get("publisher"),
                         **_text_fields(item, query, self.settings.snippet_chars)})
        return {"filters": result["filters"], "hits": hits, "count": len(hits)}

    def get_document(self, revision_id: str = "", wfa_document_id: str = ""):
        if revision_id:
            rows = self._doc_rows(revision_id=revision_id)
        elif wfa_document_id:
            rows = self._doc_rows(wfa_document_id=str(wfa_document_id))
        else:
            return {"error": "請提供 revision_id 或 wfa_document_id"}
        return {"documents": [{**self._summary(d), "source_urls": d.get("source_urls"), "adoption_reason": d.get("adoption_reason")}
                              for d in rows[:5]]} if rows else {"error": "找不到文件"}

    def list_versions(self, revision_id: str):
        rows = self._doc_rows(revision_id=revision_id)
        if not rows:
            return {"error": "找不到文件"}
        doc = rows[0]
        series = doc.get("version_series_id") or doc.get("document_family_id")
        related = {d["revision_id"]: d for d in self._doc_rows()}
        family = [d for d in related.values() if series and (d.get("version_series_id") == series or d.get("document_family_id") == series)]
        # Follow explicit supersedes edges as well; series ids may be missing on older records.
        frontier = [doc["revision_id"]]
        seen = {d["revision_id"] for d in family} | {doc["revision_id"]}
        while frontier:
            rid = frontier.pop()
            for d in related.values():
                if (rid in (d.get("supersedes") or []) or d["revision_id"] in (related.get(rid, {}).get("supersedes") or [])) and d["revision_id"] not in seen:
                    seen.add(d["revision_id"])
                    frontier.append(d["revision_id"])
        versions = [self._summary(related[r]) for r in seen if r in related]
        versions.sort(key=lambda d: (str(d.get("document_date") or ""), str(d.get("wfa_revision") or "")))
        return {"series": series, "versions": versions}

    def read_document(self, revision_id: str, start: int = 1, count: int = 4, query: str = ""):
        start, count = max(1, int(start or 1)), max(1, min(int(count or 4), 8))
        doc = self.store.document(revision_id)
        if not doc:
            return {"error": "找不到文件"}
        total, page = self.store.chunk_page(revision_id, start, count)
        ids = [point_id for point_id, _ in page]
        chunks = self.search_engine.chunks(ids)
        parts = []
        for pid in ids:
            item = chunks[pid]
            parts.append({"ref": self.citations.add(item), "chunk_index": item["chunk_index"], "location": item["location_label"],
                          **_text_fields(item, query, self.settings.read_chars)})
        return {"title": doc.get("title"), "total_chunks": total, "parts": parts,
                "next_start": start + len(ids) if start + len(ids) <= total else None}

    def list_documents(self, keyword: str = "", publisher: str = "", document_role: str = "", include_history: bool = False, limit: int = 20):
        limit = max(1, min(int(limit or 20), 50))
        rows = self._doc_rows()
        key = (keyword or "").casefold()
        matched = [d for d in rows
                   if (include_history or d.get("analysis_eligible"))
                   and (not publisher or (d.get("publisher") or "").casefold() == publisher.casefold())
                   and (not document_role or document_role.casefold() in (d.get("document_role") or "").casefold())
                   and (not key or key in (d.get("title") or "").casefold() or any(key in str(t).casefold() for t in d.get("topics") or []))]
        return {"total": len(matched), "documents": [self._summary(d) for d in matched[:limit]]}

    def zone_overview(self):
        rows = self._doc_rows()
        current = [d for d in rows if d.get("analysis_eligible")]
        topics = Counter(t for d in current for t in d.get("topics") or [])
        manifest = self.store.manifest()
        # Complete counts (not top-N) so totals always add up to current_documents.
        return {"package_id": manifest.get("package_id"), "exported_at": manifest.get("created_utc"),
                "documents": len(rows), "current_documents": len(current),
                "superseded_documents": len(rows) - len(current), "counts_scope": "current_documents",
                "by_publisher": Counter(d.get("publisher") or "未標示" for d in current).most_common(),
                "by_document_role": Counter(d.get("document_role") or "未標示" for d in current).most_common(),
                "top_topics": topics.most_common(20)}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = {"search_wifi": self.search_wifi, "get_document": self.get_document, "list_versions": self.list_versions,
                   "read_document": self.read_document, "list_documents": self.list_documents,
                   "zone_overview": self.zone_overview}.get(name)
        if handler is None:
            return {"error": f"未知的工具：{name}"}
        try:
            result = handler(**arguments)
        except TypeError as exc:
            return {"error": f"參數錯誤：{exc}"}
        self.evidence.append(json.dumps(result, ensure_ascii=False))
        return result


Llm = Callable[..., Any]  # (messages=..., tools=..., tool_choice=...) -> message with .content / .tool_calls


def _message(response: Any) -> Any:
    return response.choices[0].message


def run_agent(question: str, *, llm: Llm, tools: WifiTools, settings: AgentSettings,
              history: list[dict[str, str]] | None = None, clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    started = clock()
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for turn in (history or [])[-6:]:
        if turn.get("role") in {"user", "assistant"} and isinstance(turn.get("content"), str):
            messages.append({"role": turn["role"], "content": turn["content"][:2000]})
    messages.append({"role": "user", "content": question})
    trace: list[dict[str, Any]] = []
    answer, stop_reason = "", "answered"
    for step in range(settings.max_steps + 1):
        out_of_budget = clock() - started > settings.time_budget_seconds
        final_round = step == settings.max_steps or out_of_budget
        if final_round:
            stop_reason = "time_budget" if out_of_budget else "max_steps"
            messages.append({"role": "user", "content": "請停止查詢，只根據目前已取得的工具結果作答，並說明尚未查證的部分。"})
        message = _message(llm(messages=messages, tools=TOOLS, tool_choice="none" if final_round else "auto"))
        calls = [] if final_round else list(getattr(message, "tool_calls", None) or [])
        if not calls:
            answer = message.content or ""
            break
        messages.append({"role": "assistant", "content": message.content or "", "tool_calls": calls})
        for call in calls:
            name = call["function"]["name"]
            t0 = clock()
            try:
                arguments = json.loads(call["function"].get("arguments") or "{}")
                result = tools.call(name, arguments if isinstance(arguments, dict) else {})
            except json.JSONDecodeError:
                arguments, result = {}, {"error": "工具參數不是 JSON"}
            trace.append({"step": step + 1, "tool": name, "arguments": arguments,
                          "result_summary": _summarize(result), "ms": round((clock() - t0) * 1000)})
            messages.append({"role": "tool", "tool_call_id": call.get("id", ""), "content": json.dumps(result, ensure_ascii=False)[:12000]})
    cited = sorted(set(re.findall(r"\[(S\d+)\]", answer)), key=lambda r: int(r[1:]))
    citations = [tools.citations.items[r] for r in cited if r in tools.citations.items]
    result = {"answer": answer, "citations": citations, "trace": trace, "stop_reason": stop_reason,
              "evidence_count": len(tools.citations.items)}
    if settings.grounding and answer:
        result["grounding"] = ground(result, tools, getattr(tools.search_engine, "encoder", None), question)
    result["elapsed_ms"] = round((clock() - started) * 1000)
    log_quality(result, tools)
    return result


_quality_logger = logging.getLogger("km.wifi8.quality")


def quality_record(result: dict[str, Any], package_id: str | None = None) -> dict[str, Any]:
    """Per-answer statistics for monitoring. Counts only: never the question, answer or source text."""
    grounding = result.get("grounding") or {}
    summary = grounding.get("summary") or {}
    keys = ("claims", "claims_cited", "claims_tool_data", "values", "values_verified", "values_other_source",
            "values_tool_data", "values_not_found")
    return {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "package_id": package_id,
            "stop_reason": result.get("stop_reason"), "steps": len(result.get("trace") or []),
            "elapsed_ms": result.get("elapsed_ms"), "citations": len(result.get("citations") or []),
            "answer_chars": len(result.get("answer") or ""), "grounding_error": bool(grounding.get("error")),
            "grounding": {k: int(summary.get(k) or 0) for k in keys} if summary else None,
            "sources": summary.get("sources")}


def log_quality(result: dict[str, Any], tools: "WifiTools") -> None:
    """One structured log line per answer (worker stdout), read by scripts/wifi8_quality_check.py."""
    if os.getenv("KM_WIFI8_QUALITY_LOG", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    try:
        record = quality_record(result, getattr(tools.search_engine, "package_id", None))
        _quality_logger.info(QUALITY_LOG_PREFIX + json.dumps(record, ensure_ascii=False, separators=(",", ":")))
    except Exception:  # noqa: BLE001 - monitoring must never affect the answer
        pass


def _summarize(result: dict[str, Any]) -> str:
    if "error" in result:
        return "錯誤：" + str(result["error"])
    if "hits" in result:
        return f"{result['count']} 筆：" + "、".join(f"[{h['ref']}] {h['title']}" for h in result["hits"][:5])
    if "parts" in result:
        return f"{result['title']} 段落 {len(result['parts'])} 筆"
    if "current_documents" in result:
        return f"總覽：{result['current_documents']} 份目前版本文件"
    if isinstance(result.get("documents"), list):
        return f"{len(result['documents'])} 份文件"
    if "versions" in result:
        return f"{len(result['versions'])} 個版本"
    return "總覽"


def ground(result: dict[str, Any], tools: WifiTools, encoder=None, question: str = "") -> dict[str, Any]:
    """Grounding check of a finished answer; a failure is reported, never raised (the answer stands)."""
    from .grounding import GroundingSettings, check_answer
    try:
        return check_answer(result.get("answer") or "", tools.citations.grounding_sources(),
                            context="\n".join([question, *tools.evidence]), encoder=encoder,
                            settings=GroundingSettings.from_environment())
    except Exception as exc:  # noqa: BLE001 - the check must not hide the answer
        return {"error": f"{type(exc).__name__}: {exc}"[:300]}
