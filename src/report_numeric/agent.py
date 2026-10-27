"""Report query agent: the model picks fixed tools, the tools return values with their source cell, the answer must cite them.
Numbers are never computed by the model: comparisons and statistics come from the tools."""
from __future__ import annotations

import datetime as dt
import decimal
import json
import re
import time
from typing import Any, Callable

from . import query as q

SYSTEM_PROMPT = """你是 KM「CSIT 知識專區」的報告查詢助手，只回答 WiFi 與蜂巢式測試報告（已匯入知識庫）的內容。
規則：
1. 只能根據工具回傳的內容回答；數值、單位、設備型號、頻段、頻寬、通道一律原樣照抄，不自行計算、四捨五入或換算。需要平均、最大、最小或設備比較時，用 compare_metric。
2. 先用工具查證再作答。問題沒有指定頻段、頻寬、通道或方向時，不要自行挑選：先用工具列出可用的條件，或請使用者指定，並說明缺少什麼。
3. 每個引用到的數值或判定，句末標註來源編號，例如 [R3]；只能使用工具回傳過的編號。
4. 報告類型：wifi_throughput 是各頻段／頻寬／通道的吞吐量表；wifi_rvr 是隨衰減（dB）掃描的 Rate-vs-Range；cellular_throughput 是蜂巢式。問「各通道吞吐量」用 wifi_throughput；問衰減、RvR、角度用 wifi_rvr；問題沒說明時兩類分開查、分開回答，不可混在一起平均。查詢結果出現 truncated 時必須縮小條件重查。
5. 方向：報告的 Tx／Rx 是 STA 的視角，DUT 一律是 AP。工具的 direction=ul 是報告的 Tx（上行），dl 是 Rx（下行），total 是 Tx＋Rx。回答用「上行」「下行」並註明報告標籤。
6. 找不到的設備、條件或資料，只說明查不到什麼，不要用其他設備或條件的資料代替，也不要推測。
7. Pass／Fail 判定與門檻一律以報告為準；不要自己重新判定。value_basis 為 reported_derived 的值是報告提供的合計或通過率，回答時註明。
8. 指標的好壞方向與合理範圍尚未定義：不要使用「較佳」「較差」「進步」「退步」，只描述數值與差異。RSSI 只作診斷參考。
9. 工具回傳 quality_status 為 source_errors_accepted 的報告，來源檔有公式錯誤儲存格（錯誤格沒有當作數值），回答時簡短註明資料品質。
10. 以繁體中文回答，先給結論，再列依據；表格資料用條列或表格呈現。"""

TOOLS = [
    {"type": "function", "function": {"name": "list_products", "description": "列出知識庫中所有設備與其報告（型號、報告類型、韌體、測試日期、整體判定）。", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "get_run_info", "description": "取得某設備的測試資訊：硬體、韌體、晶片、NPI 階段、測試日期、整體判定、測試條件（例如最佳角度、乙太網路速率）、資料品質。", "parameters": {"type": "object", "properties": {"product": {"type": "string", "description": "設備型號，例如 NCQ2200B2V-D294"}}, "required": ["product"]}}},
    {"type": "function", "function": {"name": "get_measurements", "description": "查某設備的量測值（每筆附來源儲存格）。可依指標、頻段、頻寬、通道、方向、衰減、角度、協定、統計類型篩選。單位依指標：throughput Mbps、rssi dBm、latency_rtt ms。", "parameters": {"type": "object", "properties": {
        "product": {"type": "string"}, "metric": {"type": "string", "enum": sorted(q.METRICS)}, "band": {"type": "string", "description": "2.4GHz、5GHz、6GHz 或 n78"},
        "bandwidth_mhz": {"type": "integer"}, "channel": {"type": "integer"}, "direction": {"type": "string", "enum": ["dl", "ul", "total"]},
        "attenuation_db": {"type": "number", "description": "RvR 衰減（dB）"}, "angle_deg": {"type": "number"}, "protocol": {"type": "string", "enum": ["tcp", "udp"]},
        "statistic": {"type": "string", "enum": ["peak", "average", "min", "max"], "description": "只有蜂巢式的 Peak／平均／最小／最大需要；WiFi 量測不要填"}, "report_type": {"type": "string", "enum": sorted(q.REPORT_TYPES)},
        "limit": {"type": "integer", "minimum": 1, "maximum": 200}}, "required": ["product"]}}},
    {"type": "function", "function": {"name": "compare_metric", "description": "比較多個設備在同一條件下的某指標（回傳每台的筆數、平均、最小、最大）。必須指定 band 與 bandwidth_mhz；不同條件不混合。", "parameters": {"type": "object", "properties": {
        "products": {"type": "array", "items": {"type": "string"}}, "metric": {"type": "string", "enum": sorted(q.METRICS)}, "band": {"type": "string"}, "bandwidth_mhz": {"type": "integer"},
        "direction": {"type": "string", "enum": ["dl", "ul", "total"]}, "channel": {"type": "integer"}, "report_type": {"type": "string", "enum": sorted(q.REPORT_TYPES)},
        "attenuation_db": {"type": "number"}, "angle_deg": {"type": "number"}, "protocol": {"type": "string", "enum": ["tcp", "udp"]}}, "required": ["products", "metric", "band", "bandwidth_mhz", "report_type"]}}},
    {"type": "function", "function": {"name": "list_results", "description": "列出某設備的 Pass／Fail 判定項目（依報告），可只列 fail 或指定頻段、頻寬。", "parameters": {"type": "object", "properties": {
        "product": {"type": "string"}, "band": {"type": "string"}, "bandwidth_mhz": {"type": "integer"}, "result": {"type": "string", "enum": ["pass", "fail", "n/a"]},
        "report_type": {"type": "string", "enum": sorted(q.REPORT_TYPES)}, "limit": {"type": "integer"}}, "required": ["product"]}}},
    {"type": "function", "function": {"name": "get_criteria", "description": "取得某設備報告的判定門檻（參考速率與門檻，RvR 含衰減區間）。", "parameters": {"type": "object", "properties": {
        "product": {"type": "string"}, "band": {"type": "string"}, "bandwidth_mhz": {"type": "integer"}, "report_type": {"type": "string", "enum": sorted(q.REPORT_TYPES)}}, "required": ["product"]}}},
    {"type": "function", "function": {"name": "search_text", "description": "全文與語意檢索報告文字（目的、範圍、註記、判定說明、資料表的文字化列）。用於結構化工具查不到的說明性問題。", "parameters": {"type": "object", "properties": {
        "query": {"type": "string"}, "top_k": {"type": "integer", "minimum": 1, "maximum": 10}}, "required": ["query"]}}},
]
TEXT_ONLY = [t for t in TOOLS if t["function"]["name"] == "search_text"]
TEXT_ONLY_PROMPT = SYSTEM_PROMPT.replace("需要平均、最大、最小或設備比較時，用 compare_metric。", "").replace("先用工具查證再作答。問題沒有指定頻段、頻寬、通道或方向時，不要自行挑選：先用工具列出可用的條件，或請使用者指定，並說明缺少什麼。", "先用工具查證再作答。")


def _jsonable(o: Any) -> Any:
    if isinstance(o, (dt.date, dt.datetime)):
        return o.isoformat()
    if isinstance(o, decimal.Decimal):
        return float(o)
    if isinstance(o, (set, tuple)):
        return list(o)
    return str(o)


class ToolBox:
    """Read-only access for one question: a km_test connection, Qdrant (text search), and the citations the answer may use."""

    def __init__(self, conn, qdrant=None, encode: Callable | None = None, sparse: Callable | None = None, roles=q.DEFAULT_ROLES, only: set[str] | None = None) -> None:
        self.conn, self.qdrant, self.encode, self.sparse, self.roles, self.only = conn, qdrant, encode, sparse, tuple(roles), only
        self.citations: dict[str, dict] = {}
        self.evidence: list[str] = []

    def _cite(self, row: dict, **extra: Any) -> str:
        ref = f"R{len(self.citations) + 1}"
        self.citations[ref] = {"ref": ref, "document_id": row.get("document_id"), "sheet": row.get("source_sheet") or row.get("sheet"), "cell": row.get("source_cell_range") or row.get("cell"),
                               "product": row.get("dut_model") or row.get("product_id"), **extra}
        return ref

    def call(self, name: str, args: dict) -> dict:
        if self.only is not None and name not in self.only:
            return {"error": f"工具 {name} 未提供"}
        try:
            result = self._dispatch(name, args)
        except q.QueryError as exc:
            result = {"error": str(exc)}
        except (TypeError, ValueError, AttributeError) as exc:
            result = {"error": f"參數不合法：{type(exc).__name__}：{exc}"}
        self.evidence.append(json.dumps(result, ensure_ascii=False, default=_jsonable))
        return result

    def _dispatch(self, name: str, a: dict) -> dict:
        r = self.roles
        if name == "list_products":
            rows = q.list_products(self.conn, r)
            for row in rows:
                row["ref"] = self._cite({"document_id": row["document_id"], "source_sheet": "Cover", "source_cell_range": "", "dut_model": row["dut_model"]})
            return {"products": rows}
        if name == "get_run_info":
            runs = q.get_run_info(self.conn, a["product"], r)
            for run in runs:
                run["ref"] = self._cite({"document_id": run["document_id"], "source_sheet": "2. Introduction", "source_cell_range": "", "dut_model": run["dut_model"]})
            return {"runs": runs}
        if name == "get_measurements":
            args = {k: a.get(k) for k in ("product", "metric", "band", "bandwidth_mhz", "channel", "direction", "attenuation_db", "angle_deg", "protocol", "statistic", "report_type", "limit")}
            by_type = q.count_measurements(self.conn, roles=r, **{k: v for k, v in args.items() if k != "limit"})
            rows = q.get_measurements(self.conn, roles=r, **args)
            for row in rows:
                row["ref"] = self._cite(row)
            total = sum(by_type.values())
            out = {"matched_total": total, "matched_by_report_type": by_type, "returned": len(rows), "rows": rows}
            if not rows:
                keys = [k for k, v in args.items() if v is not None and k not in ("product", "limit")]
                out["no_match_hint"] = {f"移除條件 {k} 後的符合筆數": q.count_measurements(self.conn, roles=r, **{x: (None if x == k else v) for x, v in args.items() if x != "limit"}) for k in keys}
                out["note"] = "沒有任何資料符合全部條件；no_match_hint 顯示移除單一條件後的筆數，可據此調整條件或回答查不到的原因。"
            if total > len(rows):
                out["truncated"] = "符合的資料多於回傳筆數，結果不完整：請加上 report_type、頻段、頻寬、通道或方向等條件縮小範圍後再查，不可用不完整的資料作結論。"
            return out
        if name == "compare_metric":
            res = q.compare_metric(self.conn, a["products"], a["metric"], a["band"], a["bandwidth_mhz"], a.get("direction"), a.get("channel"), a.get("report_type"),
                                   a.get("attenuation_db"), a.get("angle_deg"), a.get("protocol"), r)
            for row in res["rows"]:
                row["ref"] = self._cite({"document_id": row["document_id"], "source_sheet": ", ".join(row["sheets"]), "source_cell_range": "", "dut_model": row["dut_model"]}, kind="aggregate")
            return res
        if name == "list_results":
            rows = q.list_results(self.conn, a["product"], a.get("band"), a.get("bandwidth_mhz"), a.get("result"), a.get("report_type"), a.get("limit"), r)
            for row in rows:
                row["ref"] = self._cite(row)
            return {"count": len(rows), "rows": rows}
        if name == "get_criteria":
            rows = q.get_criteria(self.conn, a["product"], a.get("band"), a.get("bandwidth_mhz"), a.get("report_type"), r)
            for row in rows:
                row["ref"] = self._cite(row)
            return {"count": len(rows), "rows": rows}
        if name == "search_text":
            return self._search(a["query"], int(a.get("top_k") or 6))
        raise q.QueryError(f"未知的工具：{name}")

    def _search(self, text: str, top_k: int) -> dict:
        from qdrant_client.models import FieldCondition, Filter, MatchAny, SparseVector
        from .vector import COLLECTION, DENSE, SPARSE
        flt = Filter(must=[FieldCondition(key="access_roles", match=MatchAny(any=list(self.roles))), FieldCondition(key="publish_status", match=MatchAny(any=["published"]))])
        lim = max(1, min(top_k, 10)) * 4
        dense = self.qdrant.query_points(COLLECTION, query=list(map(float, self.encode([text])[0])), using=DENSE, query_filter=flt, limit=lim, with_payload=True).points
        idx, vals = self.sparse(text)
        sp = self.qdrant.query_points(COLLECTION, query=SparseVector(indices=idx, values=vals), using=SPARSE, query_filter=flt, limit=lim, with_payload=True).points if idx else []
        score: dict[str, float] = {}
        by_id = {}
        for ranking in (dense, sp):
            for rank, p in enumerate(ranking, 1):
                score[str(p.id)] = score.get(str(p.id), 0.0) + 1.0 / (60 + rank)
                by_id[str(p.id)] = p
        hits = []
        for pid in sorted(score, key=lambda k: (-score[k], k))[:max(1, min(top_k, 10))]:
            pl = by_id[pid].payload
            ref = self._cite({"document_id": pl["document_id"], "source_sheet": pl.get("source_sheet"), "source_cell_range": pl.get("source_cell_range"), "dut_model": pl.get("dut_model")}, kind="text")
            hits.append({"ref": ref, "document_id": pl["document_id"], "dut_model": pl.get("dut_model"), "content_type": pl["content_type"], "text": pl["chunk_text"][:1500]})
        return {"count": len(hits), "hits": hits}


def _msg(resp: Any) -> Any:
    return resp.choices[0].message


def _call_parts(call: Any) -> tuple[str, str, str]:
    get = (lambda o, k: o[k]) if isinstance(call, dict) else (lambda o, k: getattr(o, k))
    fn = get(call, "function")
    return (get(call, "id") if (isinstance(call, dict) and "id" in call) or hasattr(call, "id") else "", get(fn, "name"), get(fn, "arguments"))


NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def ungrounded_numbers(answer: str, evidence: list[str], question: str) -> list[str]:
    """Numbers in the answer that appear in no tool result and not in the question (a ref tag like [R3] is not a number)."""
    body = re.sub(r"\[R\d+\]", " ", answer)
    seen = {m.group(0).lstrip("-").rstrip("0").rstrip(".") if "." in m.group(0) else m.group(0).lstrip("-") for e in evidence + [question] for m in NUMBER.finditer(e)}
    out = []
    for m in NUMBER.finditer(body):
        raw = m.group(0).lstrip("-")
        norm = raw.rstrip("0").rstrip(".") if "." in raw else raw
        if norm not in seen and raw not in seen and len(raw) > 1:
            out.append(m.group(0))
    return sorted(set(out))


def run_agent(question: str, *, llm: Callable[..., Any], tools: ToolBox, schema: list[dict] | None = None, system: str = SYSTEM_PROMPT, max_steps: int = 6,
              time_budget: float = 90.0, history: list[dict] | None = None) -> dict:
    started = time.monotonic()
    messages: list[dict] = [{"role": "system", "content": system}]
    for turn in (history or [])[-6:]:
        if turn.get("role") in ("user", "assistant") and isinstance(turn.get("content"), str):
            messages.append({"role": turn["role"], "content": turn["content"][:2000]})
    messages.append({"role": "user", "content": question})
    trace, answer, stop = [], "", "answered"
    schema = schema or TOOLS
    for step in range(max_steps + 1):
        final = step == max_steps or time.monotonic() - started > time_budget
        if final:
            stop = "time_budget" if step < max_steps else "max_steps"
            messages.append({"role": "user", "content": "請停止查詢，只根據目前已取得的工具結果作答，並說明尚未查證的部分。"})
        message = _msg(llm(messages=messages, tools=schema, tool_choice="none" if final else "auto"))
        calls = [] if final else list(getattr(message, "tool_calls", None) or [])
        if not calls:
            answer = message.content or ""
            break
        messages.append({"role": "assistant", "content": message.content or "", "tool_calls": calls})
        for call in calls:
            cid, name, raw = _call_parts(call)
            try:
                args = json.loads(raw or "{}")
                args = args if isinstance(args, dict) else {}
            except json.JSONDecodeError:
                args = {}
            t0 = time.monotonic()
            result = tools.call(name, args)
            trace.append({"step": step + 1, "tool": name, "arguments": args, "error": result.get("error"), "ms": round((time.monotonic() - t0) * 1000)})
            messages.append({"role": "tool", "tool_call_id": cid, "content": json.dumps(result, ensure_ascii=False, default=_jsonable)[:14000]})
    cited = sorted(set(re.findall(r"\[(R\d+)\]", answer)), key=lambda r: int(r[1:]))
    return {"answer": answer, "citations": [tools.citations[r] for r in cited if r in tools.citations], "unknown_refs": [r for r in cited if r not in tools.citations],
            "trace": trace, "stop_reason": stop, "ungrounded_numbers": ungrounded_numbers(answer, tools.evidence, question), "elapsed_ms": round((time.monotonic() - started) * 1000)}
