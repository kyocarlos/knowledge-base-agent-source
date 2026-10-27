"""Build the text chunks (Qdrant) of a Knowledge Package. Numbers live in km_test; the chunks carry the report's words and a
readable copy of each table row with its header and unit, so a text search can still find and cite them."""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import Any, Callable

TYPE_ZH = {"wifi_throughput": "WiFi OTA 吞吐量測試報告", "wifi_rvr": "WiFi 距離對速率（RvR）測試報告", "cellular_throughput": "蜂巢式 NR 吞吐量測試報告"}
DIR_ZH = {"ul": "上行(Tx)", "dl": "下行(Rx)", "total": "合計(Tx+Rx)"}
RESULT_ZH = {"pass": "Pass", "fail": "Fail", "n/a": "N/A"}


def _fmt(v: float) -> str:
    return f"{v:g}"


def _pack(lines: list[str], head: str, budget: int, count: Callable[[str], int]) -> list[str]:
    """Greedy packing under a token budget; each chunk repeats the head so it can be read alone."""
    out, cur = [], []
    for line in lines:
        trial = "\n".join([head, *cur, line])
        if cur and count(trial) > budget:
            out.append("\n".join([head, *cur]))
            cur = []
        cur.append(line)
    if cur:
        out.append("\n".join([head, *cur]))
    return out


def build_chunks(pkg: dict, count_tokens: Callable[[str], int] = lambda t: int(len(t) / 1.6), budget: int = 380) -> list[dict]:
    doc, run, dut = pkg["document"], pkg["test_run"], pkg["dut"]
    rt, model = doc["report_type"], run["dut_model"]
    tag = f"{doc['document_id']}｜{model}"
    chunks: list[dict] = []

    def add(kind: str, text: str, **extra: Any) -> None:
        chunks.append({"content_type": kind, "text": text, **extra})

    chip = dut.get("main_chipset") or "—"
    wlan = dut.get("wlan_chipset")
    wlan_txt = "；".join(f"{b} {v}" for b, v in wlan.items()) if isinstance(wlan, dict) else (wlan or "—")
    stream = dut.get("spatial_stream")
    stream_txt = "；".join(f"{b} {v}" for b, v in stream.items()) if isinstance(stream, dict) else (stream or "—")
    add("report_overview",
        f"{tag}\n{TYPE_ZH[rt]}。文件編號 {doc['document_id']}，版本 {doc['document_version']}。設備 {model}（NPI 階段 {run.get('npi_stage') or '—'}，"
        f"硬體版本 {run.get('hardware_version') or '—'}，韌體版本 {run.get('firmware_version') or '—'}，主晶片 {chip}，WLAN 晶片 {wlan_txt}，天線 {stream_txt}，"
        f"頻段 {dut.get('bands') or '—'}，乙太網路 {dut.get('ethernet_type') or '—'}）。測試日期 {run.get('test_date') or '—'}。整體判定 {run.get('overall_result') or '報告未提供'}。"
        + (f" 資料品質：來源有 {len(pkg['quality']['formula_errors'])} 個公式錯誤儲存格（已標記，未當作數值）。" if pkg["quality"]["formula_errors"] else ""))
    for issue in pkg["quality"]["issues"]:
        add("quality_note", f"{tag}\n資料品質備註（{issue['sheet']}）：{issue['detail']}")
    for b in pkg["text_blocks"]:
        add("section_text", f"{tag}\n{b['section_path']}（{b['source_sheet']}）：{b['text']}", source_sheet=b["source_sheet"], source_cell_range=b["source_cell_range"])

    results: dict[tuple, list[dict]] = defaultdict(list)
    for r in pkg["results"]:
        results[(r.get("band"), r.get("bandwidth_mhz"))].append(r)
    for (band, bw), items in sorted(results.items(), key=lambda kv: str(kv[0])):
        lines = [f"{r['item_label']}：{RESULT_ZH.get(r['result'], r['result'])}" + (f"（門檻 {_fmt(r['criteria_value'])} {r['criteria_unit']}）" if r.get("criteria_value") is not None else "") for r in items]
        for text in _pack(lines, f"{tag}\n{band} {bw}MHz 判定結果（依報告）：", budget, count_tokens):
            add("test_results", text, band=band, bandwidth_mhz=bw, source_sheet=items[0]["source_sheet"], source_cell_range=items[0]["source_cell_range"])
    crit: dict[tuple, list[dict]] = defaultdict(list)
    for c in pkg["criteria"]:
        crit[(c.get("band"), c.get("bandwidth_mhz"))].append(c)
    for (band, bw), items in sorted(crit.items(), key=lambda kv: str(kv[0])):
        lines = [f"{c.get('wireless_mode') or ''} 串流 {c.get('spatial_stream') or '—'}"
                 + (f" 衰減 {c['attenuation_range']}" if c.get("attenuation_range") else "") + f"：參考速率 {_fmt(c['reference_rate_mbps'])} Mbps，判定門檻 {_fmt(c['criteria_value'])} {c['criteria_unit']}" for c in items]
        for text in _pack(lines, f"{tag}\n{band} {bw}MHz 判定標準（門檻）：", budget, count_tokens):
            add("criteria", text, band=band, bandwidth_mhz=bw, source_sheet=items[0]["source_sheet"], source_cell_range=items[0]["source_cell_range"])
    conds = [f"{c['name']}：{_fmt(c['value']) if c.get('value') is not None else c.get('text')} {c.get('unit') or ''}" + (f"（{c['band']} {c['bandwidth_mhz']}MHz）" if c.get("band") else "") for c in pkg["conditions"]]
    if conds:
        for text in _pack(conds, f"{tag}\n測試條件：", budget, count_tokens):
            add("test_conditions", text)

    ms = pkg["measurements"]
    if rt == "wifi_throughput":
        rows: dict[tuple, dict] = defaultdict(dict)
        for m in ms:
            rows[(m["band"], m["bandwidth_mhz"], m["channel"], m["center_freq_mhz"])][(m["metric_name"], m.get("direction"))] = m
        verdict = {(r.get("band"), r.get("bandwidth_mhz"), r.get("channel")): r for r in pkg["results"] if r.get("channel") is not None}
        groups: dict[tuple, list[str]] = defaultdict(list)
        for (band, bw, ch, freq), vals in sorted(rows.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0, kv[0][2] or 0)):
            parts = []
            for key, label in ((("throughput", "ul"), "上行(Tx) 吞吐量"), (("throughput", "dl"), "下行(Rx) 吞吐量"), (("rssi", None), "RSSI")):
                if key in vals:
                    parts.append(f"{label} {_fmt(vals[key]['value'])} {vals[key]['unit']}")
            v = verdict.get((band, bw, ch))
            if v:
                parts.append(f"判定 {RESULT_ZH.get(v['result'], v['result'])}" + (f"（門檻 {_fmt(v['criteria_value'])} Mbps）" if v.get("criteria_value") is not None else ""))
            groups[(band, bw)].append(f"CH{ch}（{freq} MHz）：" + "；".join(parts))
        for (band, bw), lines in groups.items():
            for text in _pack(lines, f"{tag}\n{band} {bw}MHz 各通道吞吐量與 RSSI（Tx/Rx 為 STA 視角：Tx＝上行、Rx＝下行）：", budget, count_tokens):
                add("measurement_rows", text, band=band, bandwidth_mhz=bw, test_case_id=f"wifi_throughput:{band}:{bw}MHz", source_sheet=ms[0]["source_sheet"], source_cell_range="")
    elif rt == "wifi_rvr":
        sweeps: dict[tuple, list[dict]] = defaultdict(list)
        angles: dict[tuple, list[dict]] = defaultdict(list)
        for m in ms:
            if m["metric_name"] in ("throughput", "rssi") and m.get("attenuation_db") is not None and m.get("angle_deg") is None:
                sweeps[(m["band"], m["bandwidth_mhz"], m["channel"], m["center_freq_mhz"], m["metric_name"], m.get("direction"))].append(m)
            elif m["metric_name"] in ("throughput", "rssi") and m.get("angle_deg") is not None:
                angles[(m["band"], m["bandwidth_mhz"], m["channel"], m["center_freq_mhz"])].append(m)
        for (band, bw, ch, freq, metric, direction), items in sorted(sweeps.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0, kv[0][2] or 0, str(kv[0][4]), str(kv[0][5]))):
            items.sort(key=lambda m: m["attenuation_db"])
            label = f"{DIR_ZH[direction]}吞吐量" if metric == "throughput" else "RSSI"
            unit = items[0]["unit"]
            body = "；".join(f"{_fmt(m['attenuation_db'])} dB={_fmt(m['value'])}" for m in items)
            for text in _pack([f"CH{ch}（{freq} MHz）{label}（{unit}）依衰減：{body}"], f"{tag}\n{band} {bw}MHz RvR 衰減掃描（STA 視角：Tx＝上行、Rx＝下行）：", budget, count_tokens):
                add("measurement_rows", text, band=band, bandwidth_mhz=bw, channel=ch, test_case_id=f"wifi_rvr:{band}:{bw}MHz", source_sheet=items[0]["source_sheet"], source_cell_range=items[0]["source_cell_range"])
        for (band, bw, ch, freq), items in sorted(angles.items(), key=lambda kv: (str(kv[0][0]), kv[0][1] or 0, kv[0][2] or 0)):
            by_angle: dict[float, dict[str, str]] = defaultdict(dict)
            for m in items:
                by_angle[m["angle_deg"]][m.get("direction") or "rssi"] = f"{_fmt(m['value'])}"
            att = items[0].get("attenuation_db")
            body = "；".join(f"{_fmt(a)}°：上行 {v.get('ul', '—')}／下行 {v.get('dl', '—')}／合計 {v.get('total', '—')}／RSSI {v.get('rssi', '—')}" for a, v in sorted(by_angle.items()))
            for text in _pack([f"CH{ch}（{freq} MHz）角度表（衰減 {_fmt(att)} dB，吞吐量 Mbps、RSSI dBm）：{body}"], f"{tag}\n{band} {bw}MHz RvR 角度掃描：", budget, count_tokens):
                add("measurement_rows", text, band=band, bandwidth_mhz=bw, channel=ch, test_case_id=f"wifi_rvr:{band}:{bw}MHz", source_sheet=items[0]["source_sheet"], source_cell_range=items[0]["source_cell_range"])
        summary = [m for m in ms if m["metric_name"] in ("pass_count", "fail_count", "total_count", "pass_rate") and m.get("channel") is None]
        by_case: dict[tuple, dict] = defaultdict(dict)
        for m in summary:
            by_case[(m["band"], m["bandwidth_mhz"])][m["metric_name"]] = m["value"]
        lines = [f"{b} {w}MHz：通過 {_fmt(v.get('pass_count', 0))}／失敗 {_fmt(v.get('fail_count', 0))}／總數 {_fmt(v.get('total_count', 0))}，通過率 {_fmt(v['pass_rate']) if 'pass_rate' in v else '—'}" for (b, w), v in sorted(by_case.items(), key=lambda kv: str(kv[0]))]
        if lines:
            add("test_results", f"{tag}\nRvR 結果摘要（依報告，通過率門檻 0.8）：\n" + "\n".join(lines), source_sheet=summary[0]["source_sheet"], source_cell_range="")
        counts: dict[tuple, dict] = defaultdict(dict)
        for m in ms:
            if m["metric_name"] in ("pass_count", "fail_count") and m.get("channel") is not None:
                counts[(m["band"], m["bandwidth_mhz"])][(m["channel"], m.get("direction"), m["metric_name"])] = m["value"]
        for (band, bw), vals in counts.items():
            lines = [f"CH{ch}{DIR_ZH[d]}：通過 {_fmt(vals.get((ch, d, 'pass_count'), 0))}／失敗 {_fmt(vals.get((ch, d, 'fail_count'), 0))}" for ch, d in sorted({(c, dd) for c, dd, _ in vals}, key=lambda x: (x[0] or 0, str(x[1])))]
            for text in _pack(lines, f"{tag}\n{band} {bw}MHz RvR 各通道衰減點通過與失敗筆數（依報告）：", budget, count_tokens):
                add("test_results", text, band=band, bandwidth_mhz=bw, source_sheet="", source_cell_range="")
    else:
        cases: dict[str, list[dict]] = defaultdict(list)
        for m in ms:
            cases[m["test_case_id"]].append(m)
        for cid, items in cases.items():
            first = items[0]
            head = f"{tag}\n{first['test_case_name']}（{first['band']} 中心頻率 {first['center_freq_mhz']} MHz，頻寬 {first['bandwidth_mhz']} MHz，TDD 時槽 {first['time_slot']}）"
            lines = []
            for m in items:
                bits = [m["metric_name"]] + [x for x in (m.get("protocol"), DIR_ZH.get(m.get("direction"), "") if m.get("direction") else "", m.get("traffic_mode"), m.get("statistic"),
                                                         f"#{m['sample_index']}" if m.get("sample_index") else "") if x]
                lines.append(f"{' '.join(bits)}：{_fmt(m['value'])} {m['unit']}")
            for text in _pack(lines, head + "：", budget, count_tokens):
                add("measurement_rows", text, band=first["band"], bandwidth_mhz=first["bandwidth_mhz"], test_case_id=cid, source_sheet=first["source_sheet"], source_cell_range="")
    for i, c in enumerate(chunks):
        c["chunk_index"] = i
        c["chunk_id"] = f"{doc['document_id']}:{doc['document_version']}:{i:04d}"
        c["chunk_hash"] = "sha256:" + hashlib.sha256(c["text"].encode("utf-8")).hexdigest()
    return chunks
