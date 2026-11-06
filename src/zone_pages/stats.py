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
你只負責從句子（包含括號裡使用者補充的選擇）抽出下面的欄位，沒有說的就留空；是否要反問使用者由系統決定，不要自己猜技術、報告種類或設備。
欄位：
- needed：true 或 false
- technology："wifi" 或 "cellular"（提到 WiFi、Wi-Fi、無線、RvR 填 wifi；提到 5G、NR、蜂巢式、Small Cell、換手、Handover 填 cellular）；句子沒有說明技術就填 null
- report_type：只有句子明確指出報告種類時才填報告類型代碼（提到 RvR、衰減、角度、距離填 wifi_rvr；提到換手、Handover、Xn、NG 填 cellular_handover；明說「WiFi 吞吐量」填 wifi_throughput，明說「5G 吞吐量」填 cellular_throughput）；只說「吞吐量」而沒說技術時填 null
- products：句子提到的設備或案子型號陣列，沒提到就是空陣列
- all_products：句子（含括號）明確說「全部設備」時填 true，否則 false
- metrics：要看的指標名稱陣列，沒指定就是空陣列（代表該類型全部指標）
- filters：條件物件，鍵可用 band、center_freq_mhz、bandwidth_mhz、channel、direction、attenuation_db、angle_deg、traffic_mode、protocol、statistic、time_slot、test_cases（測試項目代碼陣列）；只放問題明確提到的條件，不要自行加入問題沒問到的條件（包含 statistic）
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


TECH_ZH = {"wifi": "WiFi", "cellular": "5G"}
GENERAL_KIND = "throughput"      # a question that names no kind of report is about this one of the technology chosen (the others, RvR and handover, must be named)


def tech_of(rt: str) -> str:
    return rt.split("_", 1)[0]


def _tech_label(tech: str) -> str:
    return TECH_ZH.get(tech, tech)


def _labels(types) -> str:
    return "、".join(REPORT_ZH.get(t, t) for t in types)


def _is(name: str, product: dict) -> bool:
    n = name.lower()
    return n in (product["id"].lower(), product["model"].lower()) or n in product["model"].lower()


def _ask(text: str, options: list[str]) -> dict:
    return {"ask": {"text": text, "options": list(dict.fromkeys(options))}}


def with_hints(plan: dict, text: str, cat: dict) -> dict:
    """What the question plainly says, found by the program and added to what the model read: a device (the full model or a part of it that has a digit, so
    "PKE3540J" finds "PKE3540J-D223"), "全部設備", and the technology when the words point to exactly one. The model can miss a short answer typed in brackets."""
    plan = dict(plan)
    names = [str(p).strip() for p in plan.get("products") or [] if str(p).strip()]
    low = text.lower()
    tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9.\-]{3,}", text) if any(c.isdigit() for c in t) and len(t) >= 5}
    for t in cat.values():
        for p in t["products"]:
            if p["model"] not in names and (p["model"].lower() in low or any(tok in p["id"].lower() or tok in p["model"].lower() for tok in tokens)):
                names.append(p["model"])
    plan["products"] = names
    if "全部設備" in text:
        plan["all_products"] = True
    if not plan.get("technology"):
        wifi, cellular = bool(re.search(r"wi-?fi|rvr", text, re.I)), bool(re.search(r"5g|handover|換手|小型基地台|蜂巢", text, re.I))
        if wifi != cellular:
            plan["technology"] = "wifi" if wifi else "cellular"
    return plan


def next_step(plan: dict, cat: dict) -> dict:
    """The fixed order of the conversation, whatever the database holds: the technology (WiFi or 5G), then the kind of report, then which project (device),
    and only then the numbers. The model only reads what the question already says; this decides what is still missing.
    Returns {"ask": {"text", "options"}} while something is missing, otherwise {"plan": the plan with its report_type set}."""
    plan = dict(plan)
    rt = plan.get("report_type") if plan.get("report_type") in cat else None
    tech = plan.get("technology") or None
    names = [str(p).strip() for p in plan.get("products") or [] if str(p).strip()]
    if rt is None and names:                       # a device that belongs to one kind of report settles the kind
        owners = [t for t in cat if (tech is None or tech_of(t) == tech) and any(_is(n, p) for n in names for p in cat[t]["products"])]
        if len(owners) > 1:
            owners = [t for t in owners if t.endswith("_" + GENERAL_KIND)] or owners
        if len(owners) == 1:
            rt = owners[0]
        elif owners:
            return _ask(f"這個設備在專區有{_labels(owners)}的報告，請問要查哪一種？", [REPORT_ZH.get(t, t) for t in owners])
    if rt is not None:
        tech = tech_of(rt)
    if tech is None:
        options = list(dict.fromkeys(["WiFi", "5G"] + [_tech_label(tech_of(t)) for t in cat]))
        return _ask(f"請問你要查的是 {' 還是 '.join(options)} 的測試報告？目前資料庫有：{_labels(cat)}。", options)
    if rt is None:                                 # the question names no kind of report: the technology's general one, otherwise the user picks
        same = [t for t in cat if tech_of(t) == tech]
        wanted = [m for m in plan.get("metrics") or [] if any(m == x["name"] for t in same for x in cat[t]["metrics"])]
        fits = [t for t in same if not wanted or any(m == x["name"] for m in wanted for x in cat[t]["metrics"])]     # the kinds that hold what was asked for
        general = f"{tech}_{GENERAL_KIND}"
        if general in fits:
            rt = general
        elif not same:
            return _ask(f"目前專區沒有{_tech_label(tech)}的測試報告數據；有的是：{_labels(cat)}。要改查哪一種？", [REPORT_ZH.get(t, t) for t in cat])
        else:
            why = f"{REPORT_ZH.get(general, general)}報告沒有你問的指標" if general in cat else f"目前沒有{_tech_label(tech)}吞吐量類的報告"
            return _ask(f"{why}；{_tech_label(tech)}的報告有：{_labels(fits or same)}。要查哪一種？", [REPORT_ZH.get(t, t) for t in fits or same])
    models = list(dict.fromkeys(p["model"] for p in cat[rt]["products"]))
    if not names and not plan.get("all_products") and len(models) > 1:
        listed = "、".join(f"{p['model']}（{p['document_id']}）" for p in cat[rt]["products"])
        return _ask(f"{REPORT_ZH.get(rt, rt)}報告有 {len(models)} 個案子（設備）：{listed}。請問要查哪一個？", models + ["全部設備"])
    plan["report_type"] = rt
    return {"plan": plan}


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
        elif key == "statistic" and len(t["dims"].get("statistic", [])) <= 1:
            continue                  # a report type with one statistic: the filter would only drop the rows that carry none
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
    """`consult(question, history)` returns {"passages": [...], "ask": None}: the passage to add, or {"ask": {"text", "options"}} while the technology, the kind of
    report or the project is still missing (see next_step). `complete` is the text model the answers use; `source` opens the database: a context manager
    yielding an object with `catalog()` and `stats(**params)`."""

    def __init__(self, complete: Callable[[list[dict]], str], source: Callable[[], AbstractContextManager]):
        self.complete, self.source = complete, source

    def consult(self, question: str, history: list[dict] | None = None) -> dict:
        nothing = {"passages": [], "ask": None}
        before = [str(t["content"])[:300] for t in (history or []) if t.get("role") == "user"][-3:]   # an answer typed in a later turn belongs to the questions before it
        asked = "前面的提問：" + "／".join(before) + f"\n目前的問題：{question}" if before else question
        try:
            with self.source() as db:
                cat = db.catalog()
                if not cat:
                    return nothing
                plan = parse_plan(self.complete([{"role": "system", "content": PLAN_PROMPT + describe(cat)}, {"role": "user", "content": asked}]))
                if plan is None:
                    return nothing
                step = next_step(with_hints(plan, asked, cat), cat)
                if "ask" in step:
                    return {"passages": [], "ask": step["ask"]}
                params = to_query(step["plan"], cat)
                if params is None:
                    return nothing
                result = db.stats(**params)
        except Exception:                          # no database, an unknown product, a refused parameter: the answer then rests on the passages
            return nothing
        docs = ", ".join(dict.fromkeys(r["document_id"] for r in result["rows"])) or params["report_type"]
        scope = "；".join(dict.fromkeys(f"{REPORT_ZH.get(r['report_type'], r['report_type'])}報告 {r['document_id']}（設備 {r['dut_model']}）" for r in result["rows"])) or None
        content = f"資料來源：{scope}\n{render(result, params)}" if scope else render_empty(params)
        return {"passages": [{"source": f"測試數據彙總（{docs}）", "revision_id": f"timescale:{docs[:40]}", "location_label": "資料庫計算結果", "publisher": "資料庫彙總",
                              "analysis_eligible": True, "content": content, "limit": MAX_CHARS, "scope": scope}], "ask": None}
