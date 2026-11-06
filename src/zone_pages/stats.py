"""Numbers of test reports for the zone's questions: the database computes them, the model only says which ones it wants.

The model is shown what the database holds (report types, products, metrics, the values each condition takes: report_numeric.stats.catalog, read per question,
so a report CSIT sent today is in it) and answers with a small plan. The plan is checked against that same catalog and run by the fixed query of
report_numeric.stats. The result becomes one numbered passage next to the retrieved ones, so the answer cites it like any other and its numbers go through the
same grounding check. The model never writes SQL, and any failure here leaves the answer to the passages alone.
"""
from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from typing import Any, Callable

from ..report_numeric import stats as rs

REPORT_ZH = {"wifi_throughput": "WiFi 吞吐量", "wifi_rvr": "WiFi RvR", "cellular_throughput": "5G 吞吐量", "cellular_handover": "5G 換手"}
REPORT_NOTE = {"wifi_throughput": "各頻段、頻寬、通道的吞吐量；問題只說「吞吐量」又是 WiFi 時用這個", "wifi_rvr": "吞吐量與 RSSI 隨衰減、角度變化；問題提到 RvR、衰減、角度、距離才用",
               "cellular_throughput": "5G／蜂巢式 Small Cell 的吞吐量；問題只說「吞吐量」又是 5G 時用這個", "cellular_handover": "5G 換手測試；問題提到換手或 Handover 才用"}
METRIC_ZH = {"throughput": "吞吐量", "rssi": "RSSI", "latency_rtt": "RTT 延遲", "rsrp": "RSRP", "rsrq": "RSRQ", "sinr": "SINR", "udp_lost_ratio": "UDP 遺失率",
             "pass_count": "通過筆數", "fail_count": "失敗筆數", "total_count": "總筆數", "pass_rate": "通過率", "latency_rtt_before_ho": "換手前延遲",
             "latency_rtt_after_ho": "換手後延遲", "throughput_before_ho": "換手前下行吞吐量", "throughput_after_ho": "換手後下行吞吐量", "ho_success": "換手成功",
             "ping_loss_count": "ping 遺失", "latency_variation": "延遲變化", "throughput_variation": "吞吐量變化"}
DIRECTION_ZH = {"dl": "下行（報告 Rx）", "ul": "上行（報告 Tx）", "total": "合計（Tx＋Rx）"}
STATISTIC_ZH = {"peak": "報告的 Peak", "average": "報告的平均", "min": "報告的最小", "max": "報告的最大", "value": "數值"}
TRAFFIC_ZH = {"unidirectional": "單向", "bidirectional": "雙向"}
MAX_CHARS = 6000
SHOWN_VALUES = 14

PLAN_PROMPT = """你把問題轉成測試報告數據的查詢計畫，只輸出一個 JSON 物件，不要其他文字。
需要「統計或比較測試報告的數值」（平均、最大、最小、成功率、總數、中位數、百分位數、某幾次到某幾次、某個條件下的數值、不同測試項目或設備的比較）才查；只問說明、流程、目的、規格文字時 needed 填 false。
一個計畫只能查一種報告類型。所有值只能從下面「資料庫現有資料」選，沒有把握的欄位留空，不要猜。
如果問題沒有說明技術（例如 WiFi 或 5G／蜂巢式）、沒有點名設備，而資料庫裡有兩種以上的報告類型都可能是它要的（例如同時有 wifi_throughput 與 cellular_throughput），不要自己挑：needed 填 true、report_type 留空、clarify 填這些候選報告類型代碼；問題已經說明技術、點名了只屬於其中一種的設備、或只有一種類型符合時，clarify 留空。
判斷哪些類型是候選時看問題用的詞：單純問「吞吐量」只考慮吞吐量類型（不含 RvR 與換手）；只有提到 RvR、衰減、角度、距離才選 RvR；只有提到換手或 Handover 才選換手；問題已說 WiFi 就只考慮 WiFi 的類型，已說 5G、蜂巢式或 Small Cell 就只考慮 5G 的類型。
欄位：
- needed：true 或 false
- report_type：報告類型代碼（需要澄清時留空）
- clarify：需要反問使用者時的候選報告類型代碼陣列，否則是空陣列
- products：問題提到的設備型號陣列，沒提到就是空陣列（代表全部設備）
- metrics：要看的指標名稱陣列，沒指定就是空陣列（代表該類型全部指標）
- filters：條件物件，鍵可用 band、center_freq_mhz、bandwidth_mhz、channel、direction、attenuation_db、angle_deg、traffic_mode、protocol、statistic、time_slot、test_cases（測試項目代碼陣列）；問題沒提到的條件不要放
- group_by：要額外分開看的條件陣列（例如逐通道看就填 ["channel"]）；不需要就是空陣列
- from_no、to_no：問題指定「第幾次到第幾次」時填整數，否則 null
資料庫現有資料：
"""


def describe(cat: dict) -> str:
    lines = []
    for rt, t in cat.items():
        lines.append(f"- {rt}（{REPORT_ZH.get(rt, rt)}" + (f"：{REPORT_NOTE[rt]}" if rt in REPORT_NOTE else "") + "）")
        lines.append("  設備：" + "、".join(dict.fromkeys(p["model"] for p in t["products"])))
        lines.append("  指標：" + "、".join(f"{m['name']}（{m['unit']}）" for m in t["metrics"]))
        for d, values in t["dims"].items():
            shown = ", ".join(str(v) for v in values[:SHOWN_VALUES]) + (f" …共 {len(values)} 個" if len(values) > SHOWN_VALUES else "")
            lines.append(f"  {d}：{shown}")
        if t["cases"]:
            lines.append("  test_cases：" + "；".join(f"{c['id']}（{c['name']}）" if c["name"] else c["id"] for c in t["cases"]))
        if any(m["numbered"] for m in t["metrics"]):
            lines.append("  可用 from_no／to_no 指定第幾次")
        lines.append("  不會被平均在一起的條件：" + "、".join(t["series"]))
    return "\n".join(lines)


def parse_plan(reply: str) -> dict | None:
    m = re.search(r"\{.*\}", reply or "", re.S)
    try:
        plan = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
    return plan if isinstance(plan, dict) and plan.get("needed") is True else None


def _bound(v: Any) -> int | None:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and 1 <= int(v) <= 10000 else None


def _known(value: Any, allowed: list) -> bool:
    return any(str(value).lower() == str(a).lower() for a in allowed)


def clarification(plan: dict, cat: dict) -> list[str]:
    """The report types to ask the user to choose from: at least two the catalog holds, and (when the question names a device) the device in more than one of them.
    The model only proposes; a device that belongs to one type settles the question, so nothing is asked then."""
    options = [rt for rt in dict.fromkeys(plan.get("clarify") or []) if rt in cat]
    names = [str(p).lower() for p in plan.get("products") or [] if str(p).strip()]
    if names:
        options = [rt for rt in options if any(n in (p["id"].lower(), p["model"].lower()) or n in p["model"].lower() for n in names for p in cat[rt]["products"])]
    return options if len(options) > 1 else []


def to_query(plan: dict, cat: dict) -> dict | None:
    """The plan as the query's parameters: every name must be one the catalog lists (a value the database does not hold is dropped, not guessed)."""
    rt = plan.get("report_type")
    if rt not in cat:
        return None
    t = cat[rt]
    metric_names = {m["name"] for m in t["metrics"]}
    filters: dict[str, Any] = {}
    for key, value in (plan.get("filters") or {}).items():
        if key == "test_cases":
            ids = {c["id"] for c in t["cases"]}
            kept = [c for c in (value if isinstance(value, list) else [value]) if c in ids]
            if kept:
                filters["test_cases"] = kept[:12]
        elif key in rs.CONDITIONS and value is not None and (key in ("attenuation_db", "angle_deg") or _known(value, t["dims"].get(key, []))):
            filters[key] = next((a for a in t["dims"].get(key, []) if str(a).lower() == str(value).lower()), value)
    return {"report_type": rt, "products": [str(p)[:60] for p in plan.get("products") or [] if str(p).strip()][:5] or None,
            "metrics": [m for m in plan.get("metrics") or [] if m in metric_names][:12] or None, "filters": filters,
            "group_by": [d for d in plan.get("group_by") or [] if d in rs.optional_dims(rt)], "from_no": _bound(plan.get("from_no")), "to_no": _bound(plan.get("to_no"))}


def _num(v: Any) -> str:
    v = float(v)
    return f"{v:.1f}" if abs(v) >= 1000 else f"{v:.4g}"


def _series_text(row: dict, series: list[str]) -> str:
    bits = []
    for d in series:
        v = row.get(d)
        if v is None or d == "test_case_id":
            continue
        bits.append({"direction": lambda: DIRECTION_ZH.get(v, v), "statistic": lambda: STATISTIC_ZH.get(v, v), "traffic_mode": lambda: TRAFFIC_ZH.get(v, v),
                     "bandwidth_mhz": lambda: f"{v}MHz", "center_freq_mhz": lambda: f"中心頻率 {v} MHz", "time_slot": lambda: f"時槽 {v}", "channel": lambda: f"CH{v}", "attenuation_db": lambda: f"衰減 {_num(v)} dB", "angle_deg": lambda: f"角度 {_num(v)}°",
                     "protocol": lambda: str(v).upper()}.get(d, lambda: str(v))())
    return "，".join(bits)


def render(result: dict, params: dict) -> str:
    rows, series = result["rows"], result["series"] + result["group_by"]
    span = ""
    if params.get("from_no") or params.get("to_no"):
        span = f"，只計第 {params.get('from_no') or 1}～{params.get('to_no') or '最後'} 次"
    lines = [f"以下由資料庫對報告的量測數據計算{span}（n 為筆數，p95 為第 95 百分位；不同{'、'.join(result['series']) or '條件'}不會被平均在一起）："]
    head = None
    for r in rows:
        key = (r["product_id"], r["document_id"], r.get("test_case_name"), tuple(r.get(d) for d in series))
        if key != head:
            title = "／".join(x for x in (r["dut_model"], r.get("test_case_name") or "", _series_text(r, series)) if x)
            lines.append(f"【{title}】（報告 {r['document_id']}）")
            head = key
        label = METRIC_ZH.get(r["metric_name"], r["metric_name"])
        unit = f" {r['unit']}" if r["unit"] and r["unit"] not in ("count", "unitless", "") else ""
        basis = "（報告提供的值）" if r["value_basis"] == "reported_derived" else ""
        if r["metric_name"] == "ho_success":
            lines.append(f"- 換手成功 {_num(r['total'])}／{r['n']} 次（第 {r['first_no']}～{r['last_no']} 次）")
        elif r["n"] == 1:
            lines.append(f"- {label}：{_num(r['average'])}{unit}{basis}")
        else:
            total = f"，合計 {_num(r['total'])}" if r["unit"] == "count" else ""
            lines.append(f"- {label}：n {r['n']}，平均 {_num(r['average'])}{unit}，最小 {_num(r['minimum'])}，最大 {_num(r['maximum'])}，中位數 {_num(r['median'])}，p95 {_num(r['p95'])}{total}{basis}")
    if result["truncated"]:
        lines.append(f"（結果超過 {rs.MAX_ROWS} 組，已截斷；請指定設備、頻段、方向或衰減等條件縮小範圍。）")
    return "\n".join(lines)[:MAX_CHARS]


def render_empty(params: dict) -> str:
    cond = "、".join(f"{k}={v}" for k, v in (params.get("filters") or {}).items()) or "未指定條件"
    return f"資料庫中沒有符合此查詢的數據（報告類型 {params['report_type']}，設備 {'、'.join(params['products'] or ['全部'])}，{cond}）。不要用其他條件的數值代替。"


class ReportStats:
    """`consult(question, history)` returns {"passages": [...], "clarify": [...]}: the passage to add, or the report types to ask the user to choose between.
    `complete` is the text model the answers use; `source` opens the database: a context manager yielding an object with `catalog()` and `stats(**params)`."""

    def __init__(self, complete: Callable[[list[dict]], str], source: Callable[[], AbstractContextManager]):
        self.complete, self.source = complete, source

    def consult(self, question: str, history: list[dict] | None = None) -> dict:
        nothing = {"passages": [], "clarify": [], "labels": {}}
        previous = next((str(t["content"])[:300] for t in reversed(history or []) if t.get("role") == "user"), "")
        asked = f"（前一個提問：{previous}）\n目前的問題：{question}" if previous else question
        try:
            with self.source() as db:
                cat = db.catalog()
                if not cat:
                    return nothing
                plan = parse_plan(self.complete([{"role": "system", "content": PLAN_PROMPT + describe(cat)}, {"role": "user", "content": asked}]))
                if plan is None:
                    return nothing
                options = clarification(plan, cat)
                if options:
                    return {"passages": [], "clarify": options, "labels": {rt: REPORT_ZH.get(rt, rt) for rt in options}}
                params = to_query(plan, cat)
                if params is None:
                    return nothing
                result = db.stats(**params)
        except Exception:                          # no database, an unknown product, a refused parameter: the answer then rests on the passages
            return nothing
        docs = ", ".join(dict.fromkeys(r["document_id"] for r in result["rows"])) or params["report_type"]
        content = render(result, params) if result["rows"] else render_empty(params)
        return {"passages": [{"source": f"測試數據彙總（{docs}）", "revision_id": f"timescale:{docs[:40]}", "location_label": "資料庫計算結果", "publisher": "資料庫彙總",
                              "analysis_eligible": True, "content": content, "limit": MAX_CHARS}], "clarify": [], "labels": {}}
