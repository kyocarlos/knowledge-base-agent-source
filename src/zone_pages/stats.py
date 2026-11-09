"""Numbers of test reports for the zone's questions: the database computes them, the model only says which ones it wants.

The model is shown what the database holds (report types, products, metrics, the values each condition takes: report_numeric.stats.catalog, read per question,
so a report CSIT sent today is in it) and answers with a small plan. The plan is checked against that same catalog and run by the fixed query of
report_numeric.stats. The result becomes one numbered passage next to the retrieved ones, so the answer cites it like any other and its numbers go through the
same grounding check. The model never writes SQL, and any failure here leaves the answer to the passages alone.
"""
from __future__ import annotations

import json
import logging
import re
from contextlib import AbstractContextManager
from typing import Any, Callable

from ..report_numeric import stats as rs

logger = logging.getLogger(__name__)

REPORT_ZH = {"wifi_throughput": "WiFi 吞吐量", "wifi_rvr": "WiFi RvR", "cellular_throughput": "5G 吞吐量", "cellular_handover": "5G 換手"}
REPORT_NOTE = {"wifi_throughput": "各頻段、頻寬、通道的吞吐量；問題只說「吞吐量」又是 WiFi 時用這個", "wifi_rvr": "吞吐量與 RSSI 隨衰減、角度變化；問題提到 RvR、衰減、角度、距離才用",
               "cellular_throughput": "5G／蜂巢式 Small Cell 的吞吐量；問題只說「吞吐量」又是 5G 時用這個", "cellular_handover": "5G 換手測試；問題提到換手或 Handover 才用"}
METRIC_ZH = {"throughput": "吞吐量", "rssi": "RSSI", "latency_rtt": "RTT 延遲", "rsrp": "RSRP", "rsrq": "RSRQ", "sinr": "SINR", "udp_lost_ratio": "UDP 遺失率",
             "pass_count": "通過筆數", "fail_count": "失敗筆數", "total_count": "總筆數", "pass_rate": "通過率", "latency_rtt_before_ho": "換手前延遲",
             "latency_rtt_after_ho": "換手後延遲", "throughput_before_ho": "換手前下行吞吐量", "throughput_after_ho": "換手後下行吞吐量", "ho_success": "換手成功",
             "ping_loss_count": "ping 遺失", "handover_duration": "換手時間", "latency_variation": "延遲變化", "throughput_variation": "吞吐量變化"}
DIRECTION_ZH = {"dl": "下行（報告 Rx）", "ul": "上行（報告 Tx）", "total": "合計（Tx＋Rx）"}
RESULT_ZH = {"pass": "Pass", "fail": "Fail", "n/a": "N/A", "error": "Error", "skipped": "Skipped"}
STATISTIC_ZH = {"peak": "報告的 Peak", "average": "報告的平均", "min": "報告的最小", "max": "報告的最大", "value": "各次量測"}
TRAFFIC_ZH = {"unidirectional": "單向", "bidirectional": "雙向"}
MAX_CHARS = 12000
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


def project_key(p: dict) -> str:
    """What makes a project (案子): its CSIT number, else its name, else (a report that came without either) its document."""
    return str(p.get("project_code") or p.get("project_name") or p["document_id"])


def mentioned_projects(text: str, cat: dict) -> set[str]:
    """The projects the text names: by their name, their number or one of their documents."""
    low = text.lower()
    out = set()
    for t in cat.values():
        for p in t["products"]:
            if any(v and str(v).lower() in low for v in (p.get("project_name"), p.get("project_code"), p["document_id"])):
                out.add(project_key(p))
    return out


def projects_of(t: dict) -> list[dict]:
    """The projects holding reports of one kind: {"key", "label", "products"}; the label is what the user picks (the project's name with its number; the device when the
    report has no project, plus the document when two would read alike)."""
    out: dict[str, dict] = {}
    for p in t["products"]:
        out.setdefault(project_key(p), {"key": project_key(p), "label": project_label(p) or p["model"], "products": []})["products"].append(p)
    found = list(out.values())
    alike = [x["label"] for x in found]
    for pj in found:
        if alike.count(pj["label"]) > 1:
            pj["label"] += "・" + pj["products"][0]["document_id"]
    return found


def _ask(text: str, options: list[str], drop: list[str] | None = None) -> dict:
    """`drop`: earlier choices in the question that the options replace (a technology that turned out to have no data), so they do not pile up as "（WiFi）（5G 換手）"."""
    return {"ask": {"text": text, "options": list(dict.fromkeys(options)), "drop": drop or []}}


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
    plan["documents"] = [p["document_id"] for t in cat.values() for p in t["products"] if p["document_id"].lower() in low]       # a report named by its document
    plan["projects"] = [k for k in dict.fromkeys(project_key(p) for t in cat.values() for p in t["products"]) if k in mentioned_projects(text, cat)]
    if re.search("全部(設備|案子|專案)", text):
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
            return _ask(f"目前專區沒有{_tech_label(tech)}的測試報告數據；有的是：{_labels(cat)}。要改查哪一種？", [REPORT_ZH.get(t, t) for t in cat], [f"（{_tech_label(tech)}）"])
        else:
            why = f"{REPORT_ZH.get(general, general)}報告沒有你問的指標" if general in cat else f"目前沒有{_tech_label(tech)}吞吐量類的報告"
            return _ask(f"{why}；{_tech_label(tech)}的報告有：{_labels(fits or same)}。要查哪一種？", [REPORT_ZH.get(t, t) for t in fits or same], [f"（{_tech_label(tech)}）"])
    plan["report_type"] = rt
    if plan.get("all_products"):
        return {"plan": plan}
    found = projects_of(cat[rt])
    chosen = [pj for pj in found if pj["key"] in (plan.get("projects") or [])]
    if not chosen and names:                       # a device: the projects that have it
        chosen = [pj for pj in found if any(_is(n, p) for n in names for p in pj["products"])]
        if len(chosen) > 1:
            return _ask(f"設備 {'、'.join(names)} 在{REPORT_ZH.get(rt, rt)}報告裡屬於 {len(chosen)} 個案子：{'；'.join(pj['label'] for pj in chosen)}。請問要查哪一個？",
                        [pj["label"] for pj in chosen] + ["全部案子"])
    if not chosen:
        if len(found) > 1:                         # several projects and none named: never pick one for the user
            listed = "；".join(f"案子 {pj['label']}（設備 {'、'.join(dict.fromkeys(p['model'] for p in pj['products']))}，文件 {'、'.join(p['document_id'] for p in pj['products'])}）" for pj in found)
            return _ask(f"{REPORT_ZH.get(rt, rt)}報告有 {len(found)} 個案子：{listed}。請問要查哪一個案子？", [pj["label"] for pj in found] + ["全部案子"])
        chosen = found                             # a single project: nothing to ask about it, the answer names it
    candidates = [p for pj in chosen for p in pj["products"]]
    picked = [p for p in candidates if p["document_id"] in (plan.get("documents") or []) or any(_is(n, p) for n in names)]
    if not picked:
        if len(candidates) > 1:                    # the project holds several reports of this kind (devices): which one
            models = [p["model"] for p in candidates]
            options = [p["model"] + ("・" + p["document_id"] if models.count(p["model"]) > 1 else "") for p in candidates]
            listed = "；".join(f"設備 {p['model']}，文件 {p['document_id']}" for p in candidates)
            where = f"案子 {chosen[0]['label']} 的" if len(chosen) == 1 else ""
            return _ask(f"{where}{REPORT_ZH.get(rt, rt)}報告有 {len(candidates)} 份：{listed}。請問要查哪一個設備？", options + ["全部設備"])
        picked = candidates
    plan["documents"] = list(dict.fromkeys(p["document_id"] for p in picked))
    plan["products"] = []
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
    docs = {p["document_id"] for p in t["products"]}
    return {"report_type": rt, "products": [str(p)[:60] for p in plan.get("products") or [] if str(p).strip()][:5] or None,
            "documents": [d for d in plan.get("documents") or [] if d in docs][:20] or None,
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
        if d == "center_freq_mhz" and row.get("channel") is not None and "channel" in series:
            continue                                  # written with its channel: "Ch1（2412 MHz）"
        bits.append({"direction": lambda: DIRECTION_ZH.get(v, v), "statistic": lambda: STATISTIC_ZH.get(v, v), "traffic_mode": lambda: TRAFFIC_ZH.get(v, v),
                     "bandwidth_mhz": lambda: f"{v}MHz", "center_freq_mhz": lambda: f"中心頻率 {v} MHz", "time_slot": lambda: f"時槽 {v}",
                     "channel": lambda: f"Ch{v}" + (f"（{row['center_freq_mhz']} MHz）" if row.get("center_freq_mhz") is not None else ""), "attenuation_db": lambda: f"衰減 {_num(v)} dB", "angle_deg": lambda: f"角度 {_num(v)}°",
                     "protocol": lambda: str(v).upper()}.get(d, lambda: str(v))())
    return "，".join(bits)


def render(result: dict, params: dict) -> str:
    rows, series = result["rows"], result["series"] + result["group_by"]
    span = ""
    if params.get("from_no") or params.get("to_no"):
        span = f"，只計第 {params.get('from_no') or 1}～{params.get('to_no') or '最後'} 次"
    lines = [f"以下由資料庫對報告的量測數據計算{span}（n 為筆數，p95 為第 95 百分位；不同{'、'.join(result['series'] + result['group_by']) or '條件'}不會被平均在一起）："]
    if "attenuation_db" in series and rows and all(r["n"] == 1 and r["metric_name"] != "ho_success" for r in rows):
        return _render_sweep(lines, result, series)
    if rows and "channel" in series and all(r["n"] == 1 and r["report_type"] == "wifi_throughput" and r["metric_name"] in ("throughput", "rssi") for r in rows):
        return _render_channels(lines, result)
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
        elif r.get("vals") and len(r["vals"]) == r["n"]:    # a few measurements of one condition (#1, #2, #3): each value, then the statistics
            nos = r.get("nos") or []
            each = "；".join(f"#{nos[i] if i < len(nos) and nos[i] is not None else i + 1} {_num(v)}" for i, v in enumerate(r["vals"]))
            lines.append(f"- {label}（各次）：{each}{unit}（n {r['n']}，平均 {_num(r['average'])}，最小 {_num(r['minimum'])}，最大 {_num(r['maximum'])}，中位數 {_num(r['median'])}）{basis}")
        else:
            total = f"，合計 {_num(r['total'])}" if r["unit"] == "count" else ""
            lines.append(f"- {label}：n {r['n']}，平均 {_num(r['average'])}{unit}，最小 {_num(r['minimum'])}，最大 {_num(r['maximum'])}，中位數 {_num(r['median'])}，p95 {_num(r['p95'])}{total}{basis}")
    return _finish(lines, result)


def _finish(lines: list[str], result: dict) -> str:
    """The lines as text within MAX_CHARS, cut at a whole line. When anything is left out the notice comes first (it is what the answer must say), never at the end where
    the cut would take it."""
    body = "\n".join(lines)
    if not result["truncated"] and len(body) <= MAX_CHARS:
        return body
    shown, size = [], 0
    for line in lines:
        if size + len(line) + 1 > MAX_CHARS - 300:
            break
        shown.append(line)
        size += len(line) + 1
    why = f"查詢結果超過 {rs.MAX_ROWS} 組，已截斷" if result["truncated"] else "內容太長，已截斷"
    return f"【注意】{why}，下面的資料不完整，回答時要說明這一點，並請使用者指定設備、頻段、頻寬、方向或衰減等條件縮小範圍。\n" + "\n".join(shown)


WIDE_RESULT_CHARS = 3000          # about what the answer model can write back in one reply (it is cut at 2000 tokens and times out after 60 s)
OVERVIEW_WORDS = re.compile(r"全部(頻段|頻寬)|只看摘要")


def band_bandwidths(rows: list[dict]) -> list[tuple]:
    """The (band, bandwidth) pairs of a result, in order, when every row has both."""
    if not rows or any(r.get("band") is None or r.get("bandwidth_mhz") is None for r in rows):
        return []
    return list(dict.fromkeys((r["band"], r["bandwidth_mhz"]) for r in rows))


def render_overview(result: dict) -> str:
    """Per band and bandwidth the range of the values (not one condition measured repeatedly: the channels and attenuation points of the report), and the verdicts."""
    groups: dict[tuple, list[float]] = {}
    for r in result["rows"]:
        groups.setdefault((r["document_id"], r["band"], r["bandwidth_mhz"], r["metric_name"], r.get("direction"), r["unit"]), []).append(float(r["average"]))
    lines = ["以下是各頻段與頻寬的數值範圍摘要（每個頻段與頻寬含多個通道或衰減點，範圍是這些不同條件的最小、最大與平均，不是同一條件重複量測）；要看逐通道數值請指定頻段與頻寬："]
    for (doc, band, bw, metric, direction, unit), vals in groups.items():
        where = f"{band} {bw}MHz" + (f"，{DIRECTION_ZH.get(direction, direction)}" if direction else "")
        u = f" {unit}" if unit and unit not in ("count", "unitless", "") else ""
        lines.append(f"- {where}，{METRIC_ZH.get(metric, metric)}：{len(vals)} 個數值，最小 {_val(min(vals))}，最大 {_val(max(vals))}，平均 {_val(sum(vals) / len(vals))}{u}")
    tally: dict[tuple, list] = {}
    for v in result.get("verdicts") or []:
        t = tally.setdefault((v["band"], v["bandwidth_mhz"]), [0, 0, v.get("criteria_value"), v.get("criteria_unit")])
        t[0 if v["result"] == "pass" else 1] += 1
    for (band, bw), (ok, bad, crit, unit) in tally.items():
        lines.append(f"- {band} {bw}MHz 判定：Pass {ok} 個通道，Fail {bad} 個通道" + (f"（基準 {_val(crit)} {unit or ''}）" if crit is not None else ""))
    return "\n".join(lines)


def _val(v: Any) -> str:
    return f"{float(v):.2f}".rstrip("0").rstrip(".")


def _render_channels(lines: list[str], result: dict) -> str:
    """A Wi-Fi throughput report as its tables: per band and bandwidth one line per channel with the uplink, downlink, RSSI and the verdict the report gives."""
    verdict = {(v["document_id"], v["band"], v["bandwidth_mhz"], v["channel"]): v for v in result.get("verdicts") or []}
    tables: dict[tuple, dict] = {}
    for r in result["rows"]:
        t = tables.setdefault((r["product_id"], r["document_id"], r.get("band"), r.get("bandwidth_mhz")), {"row": r, "channels": {}})
        c = t["channels"].setdefault(r["channel"], {"freq": r.get("center_freq_mhz")})
        c["rssi" if r["metric_name"] == "rssi" else r.get("direction") or "x"] = r["average"]
    for (_, doc, band, bw), t in tables.items():
        lines.append(f"【{t['row']['dut_model']}／{band}，{bw}MHz】（報告 {doc}；下行為報告的 Rx，上行為 Tx）")
        for ch, c in sorted(t["channels"].items()):
            bits = [f"{label} {_val(c[k])}" for k, label in (("dl", "下行"), ("ul", "上行")) if k in c]
            line = f"- Ch{ch}" + (f"（{c['freq']} MHz）" if c.get("freq") is not None else "") + "：" + "，".join(bits) + (" Mbps" if bits else "")
            if "rssi" in c:
                line += f"，RSSI {_val(c['rssi'])} dBm"
            v = verdict.get((doc, band, bw, ch))
            if v and v.get("result"):
                line += f"，判定 {RESULT_ZH.get(v['result'], v['result'])}" + (f"（基準 {_val(v['criteria_value'])} {v.get('criteria_unit') or ''}）" if v.get("criteria_value") is not None else "")
            lines.append(line)
    return _finish(lines, result)


MAX_CHARTS = 4


def channel_charts(result: dict) -> list[dict]:
    """The per-channel Wi-Fi throughput tables as chart data (one chart per band and bandwidth: Tx and Rx by channel, and the criterion line), from the same rows and verdicts
    the text lists, so the picture and the table cannot disagree. Empty for any other result."""
    rows = result["rows"]
    if not rows or "channel" not in result["series"] + result["group_by"]:
        return []
    if not all(r["n"] == 1 and r["report_type"] == "wifi_throughput" and r["metric_name"] in ("throughput", "rssi") for r in rows):
        return []
    criteria = {(v["document_id"], v["band"], v["bandwidth_mhz"], v["channel"]): v.get("criteria_value") for v in result.get("verdicts") or []}
    tables: dict[tuple, dict] = {}
    for r in rows:
        if r["metric_name"] != "throughput" or r.get("direction") not in ("dl", "ul") or r.get("channel") is None:
            continue
        t = tables.setdefault((r["document_id"], r.get("band"), r.get("bandwidth_mhz")), {"model": r["dut_model"], "ch": {}})
        t["ch"].setdefault(r["channel"], {})[r["direction"]] = float(r["average"])
    charts = []
    for (doc, band, bw), t in tables.items():
        chans = sorted(t["ch"])
        if len(chans) < 2:
            continue
        limit = [criteria.get((doc, band, bw, ch)) for ch in chans]
        charts.append({"kind": "channel_throughput", "title": f"{t['model']}／{band} {bw}MHz　吞吐量（Mbps）依通道", "source": doc, "unit": "Mbps",
                       "categories": [f"CH{ch}" for ch in chans],
                       "series": [{"name": name, "values": [t["ch"][ch].get(d) for ch in chans]} for name, d in (("Tx", "ul"), ("Rx", "dl")) if any(d in t["ch"][ch] for ch in chans)],
                       "criteria": {"name": "Criteria", "values": limit} if any(x is not None for x in limit) else None})
    return charts[:MAX_CHARTS]


def _render_sweep(lines: list[str], result: dict, series: list[str]) -> str:
    """An attenuation sweep (one value per attenuation, channel and direction): one line per metric listing the values by attenuation, as the report's table does, never
    a statistic over the channels."""
    groups: dict[tuple, dict] = {}
    for r in result["rows"]:
        key = (r["product_id"], r["document_id"], r.get("test_case_name"), tuple(r.get(d) for d in series if d != "attenuation_db"))
        g = groups.setdefault(key, {"row": r, "metrics": {}})
        g["metrics"].setdefault((r["metric_name"], r["unit"]), []).append((r.get("attenuation_db"), r["average"], r["value_basis"]))
    rest = [d for d in series if d != "attenuation_db"]
    for g in groups.values():
        r = g["row"]
        title = "／".join(x for x in (r["dut_model"], r.get("test_case_name") or "", _series_text(r, rest)) if x)
        lines.append(f"【{title}】（報告 {r['document_id']}）")
        for (metric, unit), points in g["metrics"].items():
            label = METRIC_ZH.get(metric, metric)
            unit = f" {unit}" if unit and unit not in ("count", "unitless", "") else ""
            basis = "（報告提供的值）" if any(b == "reported_derived" for _, _, b in points) else ""
            if all(a is None for a, _, _ in points):
                lines.append(f"- {label}：" + "；".join(_num(v) + unit for _, v, _ in points) + basis)
            else:
                lines.append(f"- {label}{unit}（依衰減）：" + "；".join(f"{_num(a)} dB {_num(v)}" for a, v, _ in sorted(points, key=lambda x: (x[0] is None, x[0] or 0))) + basis)
    return _finish(lines, result)


def project_label(p: dict) -> str:
    """The project (案子) as CSIT names it: the name with its number, or the number alone for a report ingested before the names were kept."""
    name, code = p.get("project_name"), p.get("project_code")
    return f"{name}（{code}）" if name and code else (name or code or "")


def scope_of(rows: list[dict], cat: dict) -> str:
    """Which project, test case, device, kind of report and document the numbers come from, one clause per report."""
    clauses = []
    for rt, doc, model in dict.fromkeys((r["report_type"], r["document_id"], r["dut_model"]) for r in rows):
        p = next((x for x in cat.get(rt, {}).get("products", []) if x["document_id"] == doc), {})
        bits = ([f"案子 {project_label(p)}"] if project_label(p) else []) + ([f"測試案例 {p['case_name']}"] if p.get("case_name") else [])
        clauses.append("，".join(bits + [f"設備 {model}", f"{REPORT_ZH.get(rt, rt)}報告 {doc}"]))
    return "；".join(clauses)


REPORT_CUES = re.compile(r"吞吐量|throughput|rvr|換手|handover|test\s*case|測試結果|rssi|延遲|rtt|通過率", re.I)       # a question about what a report holds, numbers or not


INFO_WORDS = re.compile(r"案子|專案|案件|測試案例|任務|project|case(?!\s*\d)|task", re.I)      # "Test Case 4" names a case in a question about numbers, it does not ask who the report belongs to
LIST_WORDS = re.compile(r"列出|所有|全部|數據|數值|多少|平均|最大|最小|最高|最低|比較|差多少|each|list", re.I)      # a question that asks for the numbers themselves
AVERAGE_WORDS = re.compile(r"平均|average|mean", re.I)
OTHER_STATISTIC_WORDS = re.compile(r"峰值|peak|最大|最小|max|min|三次|每次|各次|逐次", re.I)


def default_statistic(params: dict, cat: dict, text: str) -> dict:
    """A report that lists several statistics per case (its own average, the peak, each run) answers "平均" with its own average, not with every one of them."""
    values = cat.get(params["report_type"], {}).get("dims", {}).get("statistic", [])
    if "statistic" not in params["filters"] and "average" in values and len(values) > 1 and AVERAGE_WORDS.search(text) and not OTHER_STATISTIC_WORDS.search(text):
        return {**params, "filters": {**params["filters"], "statistic": "average"}}
    return params


MERGE_CHANNELS = re.compile(r"整體|合併|不分通道|(所有|全部|各)通道.{0,4}(平均|合計|總)|all channels", re.I)
CHANNEL_REPORTS = ("wifi_throughput", "wifi_rvr")


def default_channels(params: dict, cat: dict, text: str) -> dict:
    """The channels of a Wi-Fi report are different tests (each has its own value, Ch1 / Ch6 / Ch11), not repetitions of one: they are listed one by one, with their centre
    frequency, unless the question asks for them taken together."""
    t = cat.get(params["report_type"], {})
    if params["report_type"] not in CHANNEL_REPORTS or len(t.get("dims", {}).get("channel", [])) < 2 or "channel" in params["filters"] or MERGE_CHANNELS.search(text):
        return params
    optional = rs.optional_dims(params["report_type"])
    wanted = ["channel"] + (["center_freq_mhz"] if t["dims"].get("center_freq_mhz") and "center_freq_mhz" in optional else [])
    return {**params, "group_by": list(dict.fromkeys([*params["group_by"], *wanted]))}


def info_passages(question: str, cat: dict) -> list[dict]:
    """The reports' own particulars (project, test case and task as CSIT names them, device, report) as one passage, for a question that asks about them: the names
    live in the database, in no document the zone searches."""
    if not INFO_WORDS.search(question):
        return []
    lines = []
    for rt, t in cat.items():
        for p in t["products"]:
            bits = ([f"案子 {project_label(p)}"] if project_label(p) else []) + ([f"測試案例 {p['case_name']}"] if p.get("case_name") else []) \
                + ([f"任務 {p['task_name']}"] if p.get("task_name") else []) + [f"設備 {p['model']}", f"{REPORT_ZH.get(rt, rt)}報告 {p['document_id']}"]
            lines.append("- " + "，".join(bits))
        names = [str(c["name"] or c["id"]) for c in t.get("cases") or []]
        if names:      # the cases inside the report itself (Test Case 1 ... n), apart from the one CSIT names
            lines.append(f"  {REPORT_ZH.get(rt, rt)}報告內的測試案例（共 {len(names)} 個）：" + "、".join(names[:40]))
    if not lines:
        return []
    return [{"source": "報告基本資料", "revision_id": "timescale:report-info", "location_label": "資料庫（案子、測試案例、任務、設備、報告）", "publisher": "資料庫彙總", "analysis_eligible": True,
             "content": "專區裡各份測試報告所屬的案子（CSIT 的專案）、測試案例、任務、設備與報告：\n" + "\n".join(lines[:60]), "limit": MAX_CHARS}]


def render_empty(params: dict) -> str:
    cond = "、".join(f"{k}={v}" for k, v in (params.get("filters") or {}).items()) or "未指定條件"
    return f"資料庫中沒有符合此查詢的數據（報告類型 {params['report_type']}，設備 {'、'.join(params['products'] or params.get('documents') or ['全部'])}，{cond}）。不要用其他條件的數值代替。"


class ReportStats:
    """`consult(question, history)` returns {"passages": [...], "ask": None}: the passage to add, or {"ask": {"text", "options"}} while the technology, the kind of
    report or the project is still missing (see next_step). `complete` is the text model the answers use; `source` opens the database: a context manager
    yielding an object with `catalog()` and `stats(**params)`."""

    def __init__(self, complete: Callable[[list[dict]], str], source: Callable[[], AbstractContextManager]):
        self.complete, self.source = complete, source

    def consult(self, question: str, history: list[dict] | None = None) -> dict:
        nothing = {"passages": [], "ask": None}
        info: list[dict] = []
        before = [str(t["content"])[:300] for t in (history or []) if t.get("role") == "user"][-3:]   # an answer typed in a later turn belongs to the questions before it
        asked = "前面的提問：" + "／".join(before) + f"\n目前的問題：{question}" if before else question
        try:
            with self.source() as db:
                cat = db.catalog()
                if not cat:
                    return nothing
                info = info_passages(question, cat)       # who the reports belong to: asked about by name, whether or not numbers are wanted
                plan = parse_plan(self.complete([{"role": "system", "content": PLAN_PROMPT + describe(cat)}, {"role": "user", "content": asked}]))
                if plan is None:
                    if INFO_WORDS.search(question) or not REPORT_CUES.search(asked):    # a question about the projects themselves, or not about report content
                        return {"passages": info, "ask": None}
                    plan = {"needed": True}          # about a report's content: the same questions back, so it is not answered from another project's report
                    step = next_step(with_hints(plan, asked, cat), cat)
                    if "ask" in step or not LIST_WORDS.search(question):
                        return {"passages": info, "ask": step.get("ask")}
                    # the planner said "no numbers" (or answered nothing usable) to a question that asks for the data itself: the data is fetched all the same
                step = next_step(with_hints(plan, asked, cat), cat)
                if "ask" in step:
                    return {"passages": [], "ask": step["ask"]}
                params = to_query(step["plan"], cat)
                if params is None:
                    return {"passages": info, "ask": None}
                params = default_channels(default_statistic(params, cat, asked), cat, asked)
                result = db.stats(**params)
        except Exception:                          # no database, an unknown product, a refused parameter: the answer then rests on the passages
            logger.warning("test-data lookup failed for the question %r", question[:80], exc_info=True)
            return {"passages": info, "ask": None}
        docs = ", ".join(dict.fromkeys(r["document_id"] for r in result["rows"])) or params["report_type"]
        scope = scope_of(result["rows"], cat) or None
        body = render(result, params)
        charts = channel_charts(result)
        if scope and len(body) > WIDE_RESULT_CHARS:
            combos = band_bandwidths(result["rows"])
            if OVERVIEW_WORDS.search(question):
                body, charts = render_overview(result), []
            elif len(combos) > 1:                  # the model can neither read nor write this much in one answer: the user picks a band and bandwidth, or the overview
                return {"passages": info, "ask": {"text": f"符合的數據有 {len(result['rows'])} 筆，分成 {len(combos)} 個頻段與頻寬，一次列出太長。請問要看哪一個頻段與頻寬？",
                                                  "options": [f"{b} {w}MHz" for b, w in combos] + ["全部頻段（只看摘要）"]}}
        content = f"資料來源：{scope}\n{body}" if scope else render_empty(params)
        return {"passages": [{"source": f"測試數據彙總（{docs}）", "revision_id": f"timescale:{docs[:40]}", "location_label": "資料庫計算結果", "publisher": "資料庫彙總",
                              "analysis_eligible": True, "content": content, "limit": MAX_CHARS, "scope": scope}, *info], "ask": None, "charts": charts if scope else []}
