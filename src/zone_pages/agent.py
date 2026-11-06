"""Question answering of a zone page: retrieve passages of the zone's documents (and the files the user attached), ask the model to answer from them
with numbered citations, then check what the answer says against the passages it cites.

One retrieval, one model call. The model gets only the passages; it has no tool or database access. Citations are the passages the answer actually
references; every number in the answer is looked up in the cited passages, and the ones not found are reported (grounding.flagged).
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable

from .catalog import ZoneCatalog

PASSAGES = 8
FILE_PASSAGES = 3
MAX_PASSAGE_CHARS = 700
HISTORY_TURNS = 6
RESULT_TTL = 2 * 3600
HISTORY_WORDS = re.compile(r"歷史|舊版|前一版|之前的版本|版本差異")
REF = re.compile(r"\[S(\d+)\]")
NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])")

SYSTEM = """你是 KM「{zone}」的助理，只能根據下列「資料」回答，不可使用資料以外的知識或推測。
規則：
1. 每個重點後面用 [S1]、[S2] 標示依據的資料編號，只能使用資料裡出現的編號。
2. 資料裡找不到答案時，只說「在這個專區的資料裡找不到相關內容」，並說明資料裡有哪些相近的內容（若有）；不要補上一般常識或建議。
3. 不要編造型號、版本、日期、數值；數值必須和資料一致。
4. 使用與問題相同的語言（預設繁體中文），先給結論，再條列重點。
5. 回答最後另起一行，以「追問：」開頭，列出最多三個相關的追問，用「｜」分隔；沒有就省略這一行。"""
NOTHING = "在這個專區的資料裡找不到相關內容。"


def grams(text: str) -> set[str]:
    s = str(text or "").lower()
    out = set(re.findall(r"[a-z0-9][a-z0-9.\-_/]+", s))
    han = re.sub(r"[^一-鿿]", "", s)
    out.update(han[i:i + 2] for i in range(len(han) - 1))
    return out


def file_passages(records: dict[str, dict], question: str, limit: int = FILE_PASSAGES) -> list[dict]:
    """The attached files' passages that share the most words with the question (the files live only for this conversation)."""
    q = grams(question)
    scored = []
    for fid, rec in records.items():
        for chunk in rec.get("chunks", []):
            score = len(q & grams(chunk.get("text", "")))
            if score:
                scored.append((score, fid, rec, chunk))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"source": f"使用者上傳：{rec['name']}", "revision_id": f"userfile:{fid}", "location_label": chunk.get("label") or f"第 {chunk.get('index', 0) + 1} 段",
             "publisher": "使用者上傳", "analysis_eligible": True, "content": chunk.get("text", "")} for _s, fid, rec, chunk in scored[:limit]]


def split_followups(reply: str) -> tuple[str, list[str]]:
    lines = (reply or "").strip().splitlines()
    for i in range(len(lines) - 1, -1, -1):
        m = re.match(r"^\s*追問[:：]\s*(.+)$", lines[i])
        if m:
            asks = [a.strip(" 　-•") for a in re.split(r"[｜|]", m.group(1)) if a.strip(" 　-•")]
            return "\n".join(lines[:i]).strip(), asks[:3]
    return (reply or "").strip(), []


def grounding(answer: str, cited_text: str, n_sources: int, n_current: int) -> dict[str, Any]:
    body = REF.sub("", answer)
    claims = [ln for ln in re.split(r"\n+|(?<=[。！？])", answer) if len(ln.strip()) >= 8 and not ln.strip().startswith(("|", "#"))]
    cited = [ln for ln in claims if REF.search(ln)]
    values = [n for n in NUMBER.findall(body) if len(n.replace(",", "").replace(".", "")) >= 2]
    haystack = cited_text.replace(",", "")
    missing = [v for v in dict.fromkeys(values) if v.replace(",", "") not in haystack]
    return {"summary": {"claims": len(claims), "claims_cited": len(cited), "claims_tool_data": 0, "values": len(values),
                        "values_verified": sum(1 for v in values if v not in missing), "values_not_found": sum(1 for v in values if v in missing),
                        "similarity_enabled": False, "sources": {"wfa": n_sources, "current": n_current, "total": n_sources}},
            "flagged": [{"kind": "value_not_found", "value": v} for v in missing[:10]]}


class TaskStore:
    """Finished answers, kept for two hours under the asker; another account's task id finds nothing."""

    def __init__(self, redis: Any):
        self.redis = redis

    @staticmethod
    def _key(task_id: str) -> str:
        return f"zonepages:agent:result:{task_id}"

    def save(self, task_id: str, value: dict) -> None:
        self.redis.set(self._key(task_id), json.dumps(value, ensure_ascii=False), ex=RESULT_TTL)

    def get(self, task_id: str) -> dict | None:
        raw = self.redis.get(self._key(task_id))
        if raw is None:
            return None
        return json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)


class ZoneAgent:
    def __init__(self, catalog: ZoneCatalog, complete: Callable[[list[dict]], str] | None, clock: Callable[[], float] = time.monotonic):
        self.catalog, self.complete, self.clock = catalog, complete, clock

    def _messages(self, zone_label: str, question: str, history: list[dict], passages: list[dict]) -> list[dict]:
        context = "\n\n".join(f"[S{i}] {p['source']}（{p['location_label']}）\n{p['content'][:MAX_PASSAGE_CHARS]}" for i, p in enumerate(passages, 1))
        turns = [{"role": t["role"], "content": str(t["content"])[:1500]} for t in history[-HISTORY_TURNS:] if t.get("role") in ("user", "assistant")]
        return [{"role": "system", "content": SYSTEM.format(zone=zone_label)}, *turns, {"role": "user", "content": f"資料：\n{context}\n\n問題：{question}"}]

    def answer(self, *, task_id: str, zone_label: str, zone_names: list[str], question: str, history: list[dict], owner: dict, file_records: dict[str, dict],
               emit: Callable[[dict], None]) -> dict[str, Any]:
        started = self.clock()
        trace = [{"tool": "search_documents"}]
        emit({"type": "tool", "label": "搜尋專區文件"})
        hits = self.catalog.search(question, zone_names, top_k=PASSAGES, include_history=bool(HISTORY_WORDS.search(question)))
        passages = [{"source": h["doc"]["title"], "revision_id": h["doc"]["revision_id"], "location_label": h["chunk"]["location_label"], "publisher": h["doc"]["publisher"],
                     "analysis_eligible": h["doc"]["analysis_eligible"], "content": h["chunk"]["content"]} for h in hits]
        if file_records:
            emit({"type": "tool", "label": "讀取你上傳的檔案"})
            trace.append({"tool": "search_user_files"})
            passages += file_passages(file_records, question)
        passages = passages[:PASSAGES + FILE_PASSAGES]
        main, followups, cited = NOTHING, [], []
        if passages and self.complete is not None:
            emit({"type": "tool", "label": "讀取引用段落"})
            trace.append({"tool": "read_chunks"})
            reply = self.complete(self._messages(zone_label, question, history, passages))
            main, followups = split_followups(reply)
            refs = []
            for n in (int(x) for x in REF.findall(main)):
                if 1 <= n <= len(passages) and n not in refs:
                    refs.append(n)
            cited = [{"ref": f"S{n}", "source": passages[n - 1]["source"], "revision_id": passages[n - 1]["revision_id"], "location_label": passages[n - 1]["location_label"],
                      "publisher": passages[n - 1]["publisher"], "wfa_document_id": passages[n - 1]["revision_id"].split(":")[0][:8].upper(),
                      "analysis_eligible": passages[n - 1]["analysis_eligible"]} for n in refs]
        emit({"type": "tool", "label": "檢查回答依據"})
        trace.append({"tool": "check_grounding"})
        text = "\n".join(passages[int(c["ref"][1:]) - 1]["content"] for c in cited)
        docs = [c for c in cited if c["publisher"] != "使用者上傳"]
        result = {"task_id": task_id, "owner": owner, "status": "completed", "question": question, "answer_main": main, "citations": cited,
                  "stop_reason": "end_turn（完成）", "trace": trace, "grounding": grounding(main, text, len(docs), sum(1 for c in docs if c["analysis_eligible"])),
                  "extension": {"related": ("相關文件：" + "、".join(dict.fromkeys(c["source"] for c in docs[:3]))) if docs else "", "followups": followups},
                  "elapsed_ms": int((self.clock() - started) * 1000)}
        for i in range(0, len(main), 24):
            emit({"type": "delta", "text": main[i:i + 24]})
        return result
