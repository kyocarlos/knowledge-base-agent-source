"""Numbers of test reports for the zone's questions: the database computes them, the model only says which ones it wants.

One model call turns the question into a small plan (product, test cases, metrics, a range of handovers); the plan is checked against allow-lists and run
by the fixed query of report_numeric.query. The result becomes one numbered passage next to the retrieved ones, so the answer cites it like any other and its
numbers go through the same grounding check. The model never writes SQL, and any failure here leaves the answer to the passages alone.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from ..report_numeric import query as q

PLAN_PROMPT = """你把問題轉成測試報告數據的查詢計畫，只輸出一個 JSON 物件，不要其他文字。
問題需要「統計或比較測試報告的數值」（平均、最大、最小、成功率、總數、中位數、百分位數、某幾次到某幾次、不同測試項目或設備的比較）才查；只問說明、流程、目的、規格文字時 needed 填 false。
欄位：
- needed：true 或 false
- products：問題提到的設備型號陣列，沒提到就是空陣列
- modes：問題提到的換手模式陣列，xn 或 ng；沒提到就是空陣列（代表全部）
- counts：問題提到的測試次數陣列，2、10 或 100；沒提到就是空陣列（代表全部）
- metrics：要看的指標陣列，從 latency_rtt_before_ho、latency_rtt_after_ho、throughput_before_ho、throughput_after_ho、ho_success、ping_loss_count、latency_variation、throughput_variation 選；沒指定就是空陣列（代表全部）
- from_no、to_no：問題指定「第幾次到第幾次」時填整數，否則 null"""
CASE = "cellular_handover:{mode}:{count}"
LABEL = {"latency_rtt_before_ho": "換手前延遲", "latency_rtt_after_ho": "換手後延遲", "throughput_before_ho": "換手前下行吞吐量", "throughput_after_ho": "換手後下行吞吐量",
         "ho_success": "換手成功次數", "ping_loss_count": "ping 遺失", "latency_variation": "延遲變化", "throughput_variation": "吞吐量變化"}
MAX_CHARS = 3200


def _num(v: Any) -> str:
    return f"{float(v):.4g}" if abs(float(v)) < 1000 else f"{float(v):.1f}"


def parse_plan(reply: str) -> dict | None:
    m = re.search(r"\{.*\}", reply or "", re.S)
    try:
        plan = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
    return plan if isinstance(plan, dict) and plan.get("needed") is True else None


def _bound(v: Any) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= int(v) <= 10000 else None


def to_query(plan: dict) -> dict:
    """The plan as the query's parameters; anything outside the allow-lists is dropped here or refused by the query."""
    modes = [m for m in (str(x).lower() for x in plan.get("modes") or []) if m in ("xn", "ng")]
    counts = [int(c) for c in plan.get("counts") or [] if str(c).isdigit() and int(c) in (2, 10, 100)]
    cases = [CASE.format(mode=m, count=c) for m in (modes or ["xn", "ng"]) for c in (counts or [2, 10, 100])] if modes or counts else None
    return {"products": [str(p)[:60] for p in plan.get("products") or [] if str(p).strip()][:5] or None, "test_cases": cases,
            "metrics": [m for m in plan.get("metrics") or [] if m in q.HANDOVER_METRICS] or None, "from_no": _bound(plan.get("from_no")), "to_no": _bound(plan.get("to_no"))}


def render(rows: list[dict], params: dict) -> str:
    span = ""
    if params.get("from_no") or params.get("to_no"):
        span = f"，只計第 {params.get('from_no') or 1}～{params.get('to_no') or '最後'} 次"
    lines = [f"以下由資料庫對報告的逐次換手數據計算{span}（n 為筆數，p95 為第 95 百分位）："]
    case = None
    for r in rows:
        head = f"{r['dut_model']}／{r['test_case_name']}"
        if head != case:
            lines.append(f"【{head}】（報告 {r['document_id']}）")
            case = head
        unit = f" {r['unit']}" if r["unit"] and r["unit"] not in ("count", "") else ""
        if r["metric_name"] == "ho_success":
            lines.append(f"- 換手成功 {_num(r['total'])}／{r['n']} 次（第 {r['first_no']}～{r['last_no']} 次）")
        else:
            extra = f"，合計 {_num(r['total'])}" if r["metric_name"] == "ping_loss_count" else ""
            lines.append(f"- {LABEL.get(r['metric_name'], r['metric_name'])}：n {r['n']}，平均 {_num(r['average'])}{unit}，最小 {_num(r['minimum'])}，最大 {_num(r['maximum'])}，"
                         f"中位數 {_num(r['median'])}，p95 {_num(r['p95'])}{extra}")
    return "\n".join(lines)[:MAX_CHARS]


class ReportStats:
    """`passages(question)` returns the passage to add (or nothing); `complete` is the same text model the answers use, `run` takes the query's parameters."""

    def __init__(self, complete: Callable[[list[dict]], str], run: Callable[..., list[dict]], available: Callable[[], bool] = lambda: True):
        self.complete, self.run, self.available = complete, run, available

    def passages(self, question: str) -> list[dict]:
        try:
            if not self.available():
                return []
            plan = parse_plan(self.complete([{"role": "system", "content": PLAN_PROMPT}, {"role": "user", "content": question}]))
            if plan is None:
                return []
            params = to_query(plan)
            rows = self.run(**params)
        except Exception:                          # no database, an unknown product, a refused parameter: the answer then rests on the passages
            return []
        if not rows:
            return []
        docs = ", ".join(dict.fromkeys(r["document_id"] for r in rows))
        return [{"source": f"測試數據彙總（{docs}）", "revision_id": f"timescale:{rows[0]['document_id']}", "location_label": "資料庫計算結果", "publisher": "資料庫彙總",
                 "analysis_eligible": True, "content": render(rows, params)}]
