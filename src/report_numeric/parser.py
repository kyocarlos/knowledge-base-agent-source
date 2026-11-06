"""Parse Askey SIT test-report workbooks (WiFi Throughput / WiFi RvR / cellular NR throughput) into a Knowledge Package.

Everything is read from cell positions found by labels and patterns, never from fixed coordinates, and every extracted
value keeps its sheet and cell range for citation. Cells holding formula errors (#REF! ...) are never read as numbers; they
are listed under ``quality.formula_errors``.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

SCHEMA_VERSION = "1.0"
REPORT_TYPES = (("SIT-TR-WL-RvR", "wifi_rvr"), ("SIT-TR-WL-Throughput", "wifi_throughput"), ("SIT-TR-SC-NR-Throughput", "cellular_throughput"),
                ("SIT-SR-SC-NR-Handover", "cellular_handover"))
# Report categories (Wi-Fi / Cellular / Small Cell / PON / Cable). A new report type is one REPORT_TYPES entry plus a parser function.
CATEGORY = {"wifi_rvr": "wifi", "wifi_throughput": "wifi", "cellular_throughput": "small_cell", "cellular_handover": "small_cell"}
# TR = test report, SR = the handover series; the version may carry a minor part and a suffix (V13.5a)
DOC_NUMBER = re.compile(r"^SIT-[TS]R-[A-Z]{2}-[\w .-]*-V\d+[\w.]*$")
BAND = r"(2\.4GHz|5GHz|6GHz)"
# Source label -> canonical direction. Tx/Rx are the STA's view and the DUT is always the AP (domain engineers, 2026-10-21).
DIRECTION = {"tx": "ul", "rx": "dl", "uplink": "ul", "downlink": "dl", "total": "total"}
DUT_LABELS = {
    "dut model name": "model", "askey model name": "model", "customer model name": "customer_model", "hardware version": "hw_version",
    "firmware version": "fw_version", "wireless driver version": "driver_version", "npi stage": "npi_stage", "main chipset": "main_chipset",
    "main chipset model": "main_chipset", "wlan chipset": "wlan_chipset", "wlan chipset model": "wlan_chipset", "ethernet type": "ethernet_type",
    "spatial stream (tx / rx)": "spatial_stream", "frequency band (ghz)": "bands", "frequency band mode": "band_mode", "bandwidth (mhz)": "bandwidths",
    "model name": "model", "frequency band": "bands", "band": "bands",  # small-cell reports; serial number and MAC addresses are deliberately not mapped
}


def _t(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip() if value is not None else ""


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _is_error(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith("#") and value.strip().rstrip("!?").upper() in {"#REF", "#DIV/0", "#N/A", "#VALUE", "#NAME", "#NUM", "#NULL"}


def _ref(cell) -> str:
    return cell.coordinate


def _range(first, last) -> str:
    return first if first == last else f"{first}:{last}"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Package(dict):
    """Knowledge Package under construction."""


class Collector:
    def __init__(self, test_run_id: str) -> None:
        self.test_run_id = test_run_id
        self.measurements: list[dict] = []
        self.results: list[dict] = []
        self.criteria: list[dict] = []
        self.conditions: list[dict] = []
        self.blocks: list[dict] = []
        self.issues: list[dict] = []

    def measure(self, sheet: str, ref: str, test_case_id: str, metric: str, value: float, unit: str, *, name: str = "", basis: str = "measured", **dims: Any) -> None:
        self.measurements.append({"test_case_id": test_case_id, "test_case_name": name, "metric_name": metric, "value": float(value), "unit": unit,
                                  "value_basis": basis, "source_sheet": sheet, "source_cell_range": ref, **dims})

    def result(self, sheet: str, ref: str, test_case_id: str, label: str, result: str, **extra: Any) -> None:
        self.results.append({"test_case_id": test_case_id, "item_label": label, "result": _result(result), "result_basis": "report",
                             "source_sheet": sheet, "source_cell_range": ref, **extra})

    def text(self, sheet: str, ref: str, kind: str, text: str, section: str = "") -> None:
        if _t(text):
            self.blocks.append({"kind": kind, "section_path": section or sheet, "text": _t(text), "source_sheet": sheet, "source_cell_range": ref})


def _result(value: str) -> str:
    v = _t(value).lower()
    return {"pass": "pass", "fail": "fail", "n/a": "n/a", "error": "error", "skipped": "skipped"}.get(v, "n/a" if v in ("--", "") else v)


def _sheet(wb, prefix: str):
    return next((ws for ws in wb.worksheets if ws.title.strip().startswith(prefix)), None)


def _sheets(wb, pattern: str):
    return [ws for ws in wb.worksheets if re.match(pattern, ws.title.strip())]


def classify(path: Path) -> str:
    for prefix, kind in REPORT_TYPES:
        if path.name.startswith(prefix):
            return kind
    raise ValueError(f"unknown report type: {path.name}")


# The sheets each template reads (its parser looks for exactly these titles). A workbook whose name is not one of the registered prefixes (a variant such as
# SIT-TR-NR-Throughput-..., or a type CSIT names differently) is taken for a type only when its sheets say so and say one thing.
CONTENT_SIGNATURES = (("cellular_handover", re.compile(r"^4\.\d\s+(?:Xn|NG)\s+Handover", re.I)), ("wifi_rvr", re.compile(r"^3\.\d\s+RvR_\d")),
                      ("wifi_throughput", re.compile(r"^4\.\d\s+\d(?:\.\d)?\s*GHz Test", re.I)), ("cellular_throughput", re.compile(r"^4\.\s*Performance Test", re.I)))


def classify_content(path: str | Path) -> str | None:
    """The report type the workbook's sheet titles show, or None when they show none or more than one (the layout is not one of the registered templates)."""
    try:
        wb = load_workbook(path, read_only=True)
    except Exception:  # noqa: BLE001 - not a readable workbook: no type
        return None
    try:
        titles = [ws.title.strip() for ws in wb.worksheets]
    finally:
        wb.close()
    kinds = {kind for kind, rx in CONTENT_SIGNATURES if any(rx.match(t) for t in titles)}
    return kinds.pop() if len(kinds) == 1 else None


def classify_or_none(name: str, path: str | Path | None = None) -> str | None:
    """Report type for a file name, or None when no template is registered (the caller then keeps the generic document path).
    With the file's path, a document-number file name (SIT-...) that is not a registered prefix is classified by its sheets."""
    kind = next((kind for prefix, kind in REPORT_TYPES if name.startswith(prefix)), None)
    if kind is None and path is not None and name.startswith("SIT-") and name.lower().endswith(".xlsx"):
        return classify_content(path)
    return kind


def parse_report(path: str | Path, identity: dict | None = None, source_name: str | None = None) -> Package:
    """identity: optional upstream identity (CSIT) merged into the package: {"csit_id", "source_record_id", "project_id", "policy"}."""
    path = Path(path)
    name = source_name or path.name   # an upload is stored under a generated name; the original name selects the template
    report_type = classify_or_none(Path(name).name, path)
    if report_type is None:
        raise ValueError(f"unknown report type: {Path(name).name}")
    by_sheets = classify_content(path)
    wb = load_workbook(path, data_only=True)
    document_number = _doc_number(wb) or Path(name).stem
    version = document_number.rsplit("-", 1)[-1]
    test_run_id = f"TR:{document_number}"
    out = Collector(test_run_id)
    if by_sheets and by_sheets != report_type:   # the name wins (as before), but the disagreement is recorded with the report
        out.issues.append({"kind": "report_type_mismatch", "sheet": "", "detail": f"檔名對應 {report_type}，工作表看起來是 {by_sheets}"})
    errors = [{"sheet": ws.title.strip(), "cell": c.coordinate, "value": _t(c.value), "sheet_state": ws.sheet_state}
              for ws in wb.worksheets for row in ws.iter_rows() for c in row if _is_error(c.value)]
    meta = _preface(wb, out)
    dut = _dut_info(wb, out)
    if report_type == "wifi_throughput":
        _wifi_throughput(wb, out)
    elif report_type == "wifi_rvr":
        _wifi_rvr(wb, out)
    elif report_type == "cellular_handover":
        dut["peer_cell"] = _handover_peer(wb)
        _handover(wb, out, dut)
    else:
        _cellular(wb, out, document_number)
    model = dut.get("model") or _model_from_number(document_number)
    product_id = re.sub(r"\s+", "-", _t(model))
    firmware = dut.get("fw_version") or ""
    pkg = Package({
        "schema_version": SCHEMA_VERSION,
        "package_id": "PKG-" + sha256_file(path)[:16],
        "source": {"source_system": "ManualUpload", "source_file_name": name, "checksum": "sha256:" + sha256_file(path)},
        "document": {"document_id": document_number, "document_version": version, "title": _title(wb), "file_type": "xlsx",
                     "report_type": report_type, "technology": "NR" if report_type in ("cellular_throughput", "cellular_handover") else "WiFi",
                     "report_revision": meta.get("revision")},
        "test_run": {"test_run_id": test_run_id, "id_basis": "derived", "test_date": meta.get("date"), "overall_result": meta.get("judgement"),
                     "product_id": product_id, "product_id_basis": "derived", "dut_model": _t(model), "npi_stage": dut.get("npi_stage") or _stage_from_number(document_number),
                     "firmware_version": firmware or None, "firmware_id": f"{product_id}_FW_{firmware}" if firmware else None,
                     "hardware_version": dut.get("hw_version"), "chipset_vendor": _vendor(dut), "ethernet_type": dut.get("ethernet_type")},
        "dut": dut,
        "measurements": out.measurements, "results": out.results, "criteria": out.criteria, "conditions": out.conditions,
        "text_blocks": out.blocks, "quality": {"formula_errors": errors, "issues": out.issues},
    })
    pkg["document"]["category"] = CATEGORY.get(report_type)
    if identity:
        pkg["test_run"].update(id_basis="csit", csit_id=identity["csit_id"], source_record_id=identity["source_record_id"], project_id=identity.get("project_id"))
        pkg["source"]["source_system"] = identity["policy"]["source_system"]
        pkg["policy"] = identity["policy"]
    return pkg


def _doc_number(wb) -> str:
    ws = _sheet(wb, "Cover")
    for row in (ws.iter_rows() if ws else []):
        for c in row:
            if isinstance(c.value, str) and DOC_NUMBER.match(_t(c.value)):
                return _t(c.value)
    return ""


def _title(wb) -> str:
    ws = _sheet(wb, "Cover")
    for row in (ws.iter_rows() if ws else []):
        for c in row:
            if isinstance(c.value, str) and "Test Report" in c.value:
                return _t(c.value)
    return ""


def _model_from_number(number: str) -> str:
    m = re.match(r"^SIT-[TS]R-[A-Z]{2}-(?:NR-)?[A-Za-z]+-(.+?)(?:-(?:EV|DV|MP|PV))?-V\d+[\w.]*$", number)
    return m.group(1) if m else number


def _stage_from_number(number: str) -> str | None:
    m = re.search(r"-(EV|DV|MP|PV)-V\d+[\w.]*$", number)
    return m.group(1) if m else None


def _vendor(dut: dict) -> str | None:
    raw = dut.get("main_chipset")
    first = raw[0] if isinstance(raw, list) and raw else raw
    if isinstance(first, dict):
        first = next(iter(first.values()), None)
    return _t(first).title() if first else None


def _preface(wb, out: Collector) -> dict:
    ws = _sheet(wb, "1. Preface")
    meta: dict[str, Any] = {}
    if ws is None:
        return meta
    for row in ws.iter_rows():
        labels = {_t(c.value): c for c in row if isinstance(c.value, str)}
        if "Report Version" in labels:
            header = labels
            nxt = ws[row[0].row + 1]
            values = {c.column: c for c in nxt if c.value not in (None, "")}
            rev = values.get(labels["Report Version"].column)
            dte = values.get(labels["Date"].column) if "Date" in labels else None
            judge = values.get(labels["Judgement"].column) if "Judgement" in labels else None
            subj = next((values[k] for k in sorted(values) if isinstance(values[k].value, str) and len(_t(values[k].value)) > 20), None)
            meta["revision"] = int(rev.value) if rev is not None and isinstance(rev.value, (int, float)) else None
            if dte is not None and isinstance(dte.value, (datetime, date)):
                meta["date"] = (dte.value.date() if isinstance(dte.value, datetime) else dte.value).isoformat()
            if judge is not None and _t(judge.value) not in ("--", ""):
                meta["judgement"] = _result(judge.value)
            if subj is not None:
                out.text(ws.title.strip(), _ref(subj), "report_note", subj.value, "1.2 Result")
            break
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str) and re.match(r"^1\.4\s*Comment", _t(c.value)):
                for r in range(c.row + 2, min(c.row + 8, ws.max_row + 1)):
                    cell = ws.cell(r, 2)
                    if _t(cell.value):
                        out.text(ws.title.strip(), _ref(cell), "comment", cell.value, "1.4 Comment")
    return meta


def _dut_info(wb, out: Collector) -> dict:
    """DUT information block: ``label：`` cells with values to their right; a band or ``LAN`` sub-label attaches to the nearest
    active label to its left, so both layouts (one pair per row, two pairs per row) read the same way."""
    ws = _sheet(wb, "2. Introduction")
    dut: dict[str, Any] = {}
    if ws is None:
        return dut
    start = next((c.row for row in ws.iter_rows(max_row=30) for c in row if isinstance(c.value, str) and _t(c.value) in ("DUT Information", "Small Cell Information", "Small Cell A Information")), None)
    if start is None:
        return dut
    sub_label = re.compile(r"^(2\.4GHz|5GHz|6GHz|LAN)\s*[:：]$")
    active: dict[int, str] = {}
    values: dict[tuple[str, str | None], list[str]] = {}
    for r in range(start + 1, min(start + 30, ws.max_row + 1)):
        tokens = [(c.column, _t(c.value)) for c in ws[r] if c.value not in (None, "") and c.column <= 10]  # columns after J hold the template's Example
        if tokens and (tokens[0][1] in ("Engineer", "Test Laboratory Location") or tokens[0][1].startswith("Small Cell B")):
            break  # handover reports describe a second small cell right below the first; it is read separately (_handover_peer)
        if not tokens and values and r > start + 12:
            break
        target: tuple[str, str | None] | None = None
        for col, text in tokens:
            m = sub_label.match(text)
            if m:
                left = [c for c in active if c < col]
                target = (active[max(left)], m.group(1)) if left else None
            elif text.endswith(("：", ":")):
                key = DUT_LABELS.get(text.rstrip("：: ").strip().lower())
                if key:
                    active[col] = key
                    target = (key, None)
                else:
                    target = None
            elif target is not None and text not in ("--",):
                values.setdefault(target, []).append(text)
    for (key, sub), parts in values.items():
        joined = " ".join(parts)
        if sub:
            dut.setdefault(key, {})
            if isinstance(dut[key], dict):
                dut[key][sub] = joined
        else:
            dut[key] = joined
    for name in ("2.1 Purpose", "2.2 Scope"):
        for row in ws.iter_rows():
            if any(isinstance(c.value, str) and _t(c.value).startswith(name) for c in row):
                r0 = row[0].row
                cells = [ws.cell(r, 1) for r in range(r0 + 1, min(r0 + 6, ws.max_row + 1)) if _t(ws.cell(r, 1).value) and not re.match(r"^2\.\d", _t(ws.cell(r, 1).value))]
                for cell in cells[:3]:
                    out.text(ws.title.strip(), _ref(cell), "section_text", cell.value, name)
                break
    return dut


# ----------------------------------------------------------------------------- WiFi Throughput
def _wifi_throughput(wb, out: Collector) -> None:
    block = re.compile(r"^(\d+\.\d+\.\d+)\s+" + BAND + r"\s*-\s*Bandwidth\s*(\d+)\s*MHz")
    for ws in wb.worksheets:
        title = ws.title.strip()
        if not re.match(r"^4\.\d", title):
            continue
        if "Concurrent" in title:
            numeric = sum(1 for row in ws.iter_rows() for c in row if _num(c.value) is not None and c.column > 2)
            if numeric == 0:
                out.issues.append({"kind": "no_data", "sheet": title, "detail": "雙頻同時測試工作表沒有任何數值（結果欄為公式錯誤）"})
            continue
        r = 1
        while r <= ws.max_row:
            m = block.match(_t(ws.cell(r, 1).value))
            if not m:
                r += 1
                continue
            section, band, bw = m.group(1), m.group(2), int(m.group(3))
            case_id, case_name = f"wifi_throughput:{band}:{bw}MHz", _t(ws.cell(r, 1).value)
            rr = r + 1
            while rr <= ws.max_row and not re.match(r"^\d{4}\s*MHz", _t(ws.cell(rr, 1).value)):
                rr += 1
                if rr - r > 8:
                    break
            while rr <= ws.max_row:
                a, b = _t(ws.cell(rr, 1).value), _t(ws.cell(rr, 2).value)
                mf = re.match(r"^(\d{4})\s*MHz", a)
                mc = re.match(r"^CH\s*(\d+)", b, re.I)
                if not (mf and mc):
                    break
                freq, ch = int(mf.group(1)), int(mc.group(1))
                dims = dict(band=band, bandwidth_mhz=bw, channel=ch, center_freq_mhz=freq, wireless_mode=None)
                tx, rx, rssi, res, crit = (ws.cell(rr, k) for k in (3, 4, 5, 6, 7))
                if _num(tx.value) is not None:
                    out.measure(title, _ref(tx), case_id, "throughput", tx.value, "Mbps", name=case_name, direction="ul", direction_source_label="Tx", protocol="tcp", **dims)
                if _num(rx.value) is not None:
                    out.measure(title, _ref(rx), case_id, "throughput", rx.value, "Mbps", name=case_name, direction="dl", direction_source_label="Rx", protocol="tcp", **dims)
                if _num(rssi.value) is not None:
                    out.measure(title, _ref(rssi), case_id, "rssi", rssi.value, "dBm", name=case_name, **dims)
                if _t(res.value) and not _is_error(res.value):
                    out.result(title, _ref(res), case_id, f"{band} - {bw}MHz - CH{ch}", res.value, band=band, bandwidth_mhz=bw, channel=ch,
                               criteria_value=_num(crit.value), criteria_unit="Mbps", criteria_basis="report")
                rr += 1
            r = rr
    summary = _sheet(wb, "3.Test Result Summary") or _sheet(wb, "3. Test Result Summary")
    if summary is not None:
        title = summary.title.strip()
        for row in summary.iter_rows():
            sec = _t(row[0].value) if row else ""
            if re.match(r"^4\.\d\.\d$", sec):
                label = _t(summary.cell(row[0].row, 3).value)
                res = summary.cell(row[0].row, 8)
                m = re.match(BAND + r"\s*-\s*(\d+)MHz", label)
                if m and _t(res.value):
                    out.result(title, _ref(res), f"wifi_throughput:{m.group(1)}:{m.group(2)}MHz", label + "（摘要）", res.value, band=m.group(1), bandwidth_mhz=int(m.group(2)),
                               channel=None, criteria_basis="report")
    crit = _sheet(wb, "4. Criteria")
    if crit is not None:
        title = crit.title.strip()
        eth = next(((crit.cell(r, 2)) for r in range(1, 14) if _t(crit.cell(r, 1).value) == "Ethernet Speed"), None)
        eth_speed = _num(eth.value) if eth is not None else None
        if eth is not None and eth_speed is not None:
            out.conditions.append({"name": "ethernet_speed", "value": eth_speed, "unit": "Mbps", "band": None, "bandwidth_mhz": None, "source_sheet": title, "source_cell_range": _ref(eth)})
        mode = next((_t(crit.cell(r, 2).value) for r in range(1, 14) if _t(crit.cell(r, 1).value).startswith("Mode of DUT")), None)
        band = None
        for r in range(8, crit.max_row + 1):
            a, c, d, e = crit.cell(r, 1).value, crit.cell(r, 3).value, crit.cell(r, 4).value, crit.cell(r, 5).value
            if isinstance(a, str) and re.search(r"GHz", a):
                band = re.match(BAND, _t(a)).group(1) if re.match(BAND, _t(a)) else band
            if isinstance(c, str) and re.match(r"^\d+MHz", _t(c)) and _num(d) is not None and _num(e) is not None:
                out.criteria.append({"band": band, "bandwidth_mhz": int(re.match(r"\d+", _t(c)).group(0)), "spatial_stream": _t(crit.cell(r, 2).value) or None,
                                     "wireless_mode": mode, "attenuation_range": None, "reference_rate_mbps": float(d), "criteria_value": float(e), "criteria_unit": "Mbps",
                                     "criteria_basis": "report", "source_sheet": title, "source_cell_range": _range(f"{get_column_letter(3)}{r}", f"{get_column_letter(5)}{r}")})


# ----------------------------------------------------------------------------- WiFi RvR
def _wifi_rvr(wb, out: Collector) -> None:
    sweep = re.compile(r"^" + BAND + r"\s*-\s*(\d+)MHz\s*-\s*(Tx\. Throughput|Rx\. Throughput|RSSI Value)")
    for ws in wb.worksheets:
        title = ws.title.strip()
        if not (re.match(r"^3\.\d", title) and "RvR_" in title):
            continue
        band_bw = re.match(r"^3\.\d\s+RvR_(\d(?:\.\d)?)G-(\d+)M", title)
        band = f"{band_bw.group(1)}GHz" if band_bw else None
        bw = int(band_bw.group(2)) if band_bw else None
        case_id = f"wifi_rvr:{band}:{bw}MHz"
        best = None
        for row in ws.iter_rows(max_row=12):
            for c in row:
                if isinstance(c.value, str) and _t(c.value).startswith("Best Angle"):
                    nxt = next((x for x in ws[c.row] if x.column > c.column and _num(x.value) is not None), None)
                    best = nxt
                    break
        att_cell = next((c for row in ws.iter_rows(max_row=12) for c in row if isinstance(c.value, str) and re.match(r"^Attenuation\s*:\s*\d", _t(c.value))), None)
        angle_att = float(re.search(r"(\d+(?:\.\d+)?)", _t(att_cell.value)).group(1)) if att_cell else None
        if best is not None:
            out.conditions.append({"name": "best_angle", "value": float(best.value), "unit": "deg", "band": band, "bandwidth_mhz": bw, "source_sheet": title, "source_cell_range": _ref(best)})
        angle_hdr = next((r for r in range(1, 14) if any(isinstance(ws.cell(r, k).value, str) and re.match(r"^\d+°$", _t(ws.cell(r, k).value)) for k in range(3, 20))), None)
        if angle_hdr:
            angles = {k: int(_t(ws.cell(angle_hdr, k).value).rstrip("°")) for k in range(3, 30) if isinstance(ws.cell(angle_hdr, k).value, str) and re.match(r"^\d+°$", _t(ws.cell(angle_hdr, k).value))}
            channel = freq = None
            r = angle_hdr + 1
            while r <= ws.max_row and r < angle_hdr + 40:
                a, b = _t(ws.cell(r, 1).value), _t(ws.cell(r, 2).value)
                m = re.match(r"^(\d{4})\s*MHz\s*/?\s*\(Ch(\d+)\)", a, re.I)
                if m:
                    freq, channel = int(m.group(1)), int(m.group(2))
                if re.match(r"^3\.\d\.\d", a):
                    break
                kind = {"Tx": ("throughput", "Mbps", "ul", "measured"), "Rx": ("throughput", "Mbps", "dl", "measured"),
                        "Total": ("throughput", "Mbps", "total", "reported_derived"), "RSSI Value": ("rssi", "dBm", None, "measured")}.get(b)
                if kind and channel is not None:
                    metric, unit, direction, basis = kind
                    for k, ang in angles.items():
                        cell = ws.cell(r, k)
                        if direction == "total" and not (_num(ws.cell(r - 2, k).value) is not None and _num(ws.cell(r - 1, k).value) is not None):
                            if _num(cell.value) is not None and not any(i["sheet"] == title and i["kind"] == "angle_not_measured" for i in out.issues):
                                out.issues.append({"kind": "angle_not_measured", "sheet": title, "detail": "角度表的 Tx、Rx 是 '--'（未量測），報告的 Total 為 0，未收錄"})
                            continue
                        if _num(cell.value) is not None:
                            out.measure(title, _ref(cell), case_id, metric, cell.value, unit, name=f"{band} - {bw}MHz 角度掃描", basis=basis, band=band, bandwidth_mhz=bw,
                                        channel=channel, center_freq_mhz=freq, direction=direction, direction_source_label=b if direction else None,
                                        angle_deg=float(ang), attenuation_db=angle_att, protocol="tcp" if metric == "throughput" else None)
                elif not (a or b) and r > angle_hdr + 2:
                    break
                r += 1
        r = 1
        while r <= ws.max_row:
            m = sweep.match(_t(ws.cell(r, 1).value))
            if not m:
                r += 1
                continue
            sb, sbw, kind_label = m.group(1), int(m.group(2)), m.group(3)
            metric, unit, direction, label = {"Tx. Throughput": ("throughput", "Mbps", "ul", "Tx"), "Rx. Throughput": ("throughput", "Mbps", "dl", "Rx"),
                                              "RSSI Value": ("rssi", "dBm", None, None)}[kind_label]
            hdr = next((x for x in range(r + 1, r + 4) if _t(ws.cell(x, 1).value).startswith("Attenuation")), None)
            if hdr is None:
                r += 1
                continue
            atts = {k: float(ws.cell(hdr, k).value) for k in range(3, 40) if _num(ws.cell(hdr, k).value) is not None}
            pass_col = next((k for k in range(20, 40) if _t(ws.cell(hdr + 1, k).value) == "Pass"), None)
            rr = hdr + 1
            while rr <= ws.max_row:
                a, b = _t(ws.cell(rr, 1).value), _t(ws.cell(rr, 2).value)
                mf = re.match(r"^(\d{4})\s*MHz", a)
                mc = re.match(r"^Ch(\d+)", b, re.I)
                if not (mf and mc):
                    if rr <= hdr + 2 and (a.startswith("Channel") or not (a or b)):
                        rr += 1  # the header row under the attenuation axis
                        continue
                    break
                freq, ch = int(mf.group(1)), int(mc.group(1))
                for k, att in atts.items():
                    cell = ws.cell(rr, k)
                    if _num(cell.value) is not None:
                        out.measure(title, _ref(cell), case_id, metric, cell.value, unit, name=f"{sb} - {sbw}MHz 衰減掃描", band=sb, bandwidth_mhz=sbw, channel=ch,
                                    center_freq_mhz=freq, direction=direction, direction_source_label=label, attenuation_db=att,
                                    protocol="tcp" if metric == "throughput" else None)
                if pass_col and metric == "throughput":
                    for off, name in ((0, "pass_count"), (1, "fail_count")):
                        cell = ws.cell(rr, pass_col + off)
                        if _num(cell.value) is not None:
                            out.measure(title, _ref(cell), case_id, name, cell.value, "count", name=f"{sb} - {sbw}MHz 衰減掃描", basis="reported_derived", band=sb,
                                        bandwidth_mhz=sbw, channel=ch, center_freq_mhz=freq, direction=direction, direction_source_label=label)
                rr += 1
            r = rr
    summary = _sheet(wb, "3. Test Result Summary")
    if summary is not None:
        title = summary.title.strip()
        hdr = next((c.row for row in summary.iter_rows() for c in row if isinstance(c.value, str) and _t(c.value) == "Wireless Mode"), None)
        if hdr:
            cols = {k: re.match(BAND + r"\s*-\s*(\d+)MHz", _t(summary.cell(hdr, k).value)) for k in range(2, 14)}
            rows = {_t(summary.cell(r, 1).value): r for r in range(hdr + 1, hdr + 8)}
            for k, m in cols.items():
                if not m:
                    continue
                band, bw = m.group(1), int(m.group(2))
                cid = f"wifi_rvr:{band}:{bw}MHz"
                for label, metric, unit in (("Pass", "pass_count", "count"), ("Fail", "fail_count", "count"), ("Total", "total_count", "count"), ("Pass Rate", "pass_rate", "ratio")):
                    cell = summary.cell(rows[label], k) if label in rows else None
                    if cell is not None and _num(cell.value) is not None:
                        out.measure(title, _ref(cell), cid, metric, cell.value, unit, name=f"{band} - {bw}MHz 摘要", basis="reported_derived", band=band, bandwidth_mhz=bw)
                j = summary.cell(rows["Judgement"], k) if "Judgement" in rows else None
                c = summary.cell(rows["Criteria"], k) if "Criteria" in rows else None
                if j is not None and _t(j.value):
                    out.result(title, _ref(j), cid, f"{band} - {bw}MHz（通過率判定）", j.value, band=band, bandwidth_mhz=bw, channel=None,
                               criteria_value=_num(c.value) if c is not None else None, criteria_unit="ratio", criteria_basis="report")
    crit = _sheet(wb, "4. Criteria")
    if crit is not None:
        title = crit.title.strip()
        mode = _t(crit.cell(9, 2).value)
        ranges: list[str] = []
        band = None
        for r in range(10, crit.max_row + 1):
            a, b, c, d = (_t(crit.cell(r, k).value) for k in (1, 2, 3, 4))
            if a == "Mode":
                mm = re.match(BAND, d)
                band = mm.group(1) if mm else band
                continue
            if not a and re.match(r"^0|^\d", d) and _num(crit.cell(r, 3).value) is None:
                ranges = [_t(crit.cell(r, k).value) for k in range(4, 9)]
                continue
            ref_rate = _num(crit.cell(r, 3).value)
            m = re.match(r"^" + BAND + r"\s*/\s*(\d+)MHz", a)
            if m and ref_rate and ranges:
                for off, rng in enumerate(ranges):
                    val = _num(crit.cell(r, 4 + off).value)
                    if val is not None:
                        out.criteria.append({"band": m.group(1), "bandwidth_mhz": int(m.group(2)), "spatial_stream": b or None, "wireless_mode": a, "attenuation_range": rng + " dB",
                                             "reference_rate_mbps": float(ref_rate), "criteria_value": float(val), "criteria_unit": "Mbps", "criteria_basis": "report",
                                             "source_sheet": title, "source_cell_range": _range(f"A{r}", f"H{r}")})
        eth = next((crit.cell(r, 2) for r in range(1, 12) if _t(crit.cell(r, 1).value).startswith("AP Ethernet")), None)
        if eth is not None and _t(eth.value):
            out.conditions.append({"name": "ap_ethernet_type", "value": None, "text": _t(eth.value), "unit": None, "band": None, "bandwidth_mhz": None, "source_sheet": title, "source_cell_range": _ref(eth)})


# ----------------------------------------------------------------------------- cellular NR throughput
def _slot_dims(band_txt: str, bw: Any, slot: str | None) -> dict:
    mb = re.match(r"^(n\d+\w*?)_([\d.]+)GHz", _t(band_txt))
    return dict(band=mb.group(1) if mb else (_t(band_txt) or None), center_freq_mhz=int(round(float(mb.group(2)) * 1000)) if mb else None,
                bandwidth_mhz=int(bw) if _num(bw) is not None else None, time_slot=_t(slot) or None)


def _flag_band(out: Collector, d: dict, sheet: str, case: Any) -> None:
    if d["center_freq_mhz"] is None and not any(i.get("detail", "").endswith(f"Test Case {case}") and i["sheet"] == sheet for i in out.issues):
        out.issues.append({"kind": "unparsed_band", "sheet": sheet, "detail": f"頻段欄位『{d['band']}』不是 nXX_頻率GHz 格式（來源資料問題），中心頻率未知：Test Case {case}"})


def _case_id(d: dict) -> str:
    """The same band, bandwidth and time slot are tested at different centre frequencies, so the frequency is part of the id."""
    return f"cellular_throughput:{d['band']}@{d['center_freq_mhz']}:{d['bandwidth_mhz']}MHz:{d['time_slot']}"


def _cellular(wb, out: Collector, document_number: str) -> None:
    """Summary sheet = one value per test case and metric (4 cases per block, two columns each); the performance sheet adds the
    three runs and the peak per case, and RTT / RSRP / RSRQ / SINR. Columns after J are the template's Example and are ignored."""
    summary = _sheet(wb, "3. Test Result Summary")
    if summary is not None:
        title = summary.title.strip()
        r = 1
        while r <= summary.max_row:
            if _t(summary.cell(r, 1).value) != "Test Case":
                r += 1
                continue
            cols = {k: int(summary.cell(r, k).value) for k in range(2, 11) if _num(summary.cell(r, k).value) is not None}
            end = r + 1
            while end <= summary.max_row and _t(summary.cell(end, 1).value) != "Test Case":
                end += 1
            rows = {}
            proto = None
            for rr in range(r + 1, end):
                a, b = _t(summary.cell(rr, 1).value), _t(summary.cell(rr, 2).value)
                if a.startswith("TCP"):
                    proto = "tcp"
                elif a.startswith("UDP"):
                    proto = "udp"
                elif a.startswith("Latency"):
                    proto = None
                    rows["latency"] = rr
                if a in ("Band", "Bandwidth", "WAN Interface") or a.endswith("Time Slot"):
                    rows["slot" if a.endswith("Time Slot") else a] = rr
                if b in ("DL", "UL", "Bidirection") and proto:
                    rows[(proto, b)] = rr
            for k, case in cols.items():
                d = _slot_dims(summary.cell(rows["Band"], k).value, summary.cell(rows["Bandwidth"], k).value, summary.cell(rows["slot"], k).value)
                _flag_band(out, d, title, case)
                cid = _case_id(d)
                for key, rr in rows.items():
                    if isinstance(key, tuple):
                        proto, label = key
                        if label == "Bidirection":
                            for col, direction, src in ((k, "dl", "Bidirection - DL"), (k + 1, "ul", "Bidirection - UL")):
                                cc = summary.cell(rr, col)
                                if _num(cc.value) is not None:
                                    out.measure(title, _ref(cc), cid, "throughput", cc.value, "Mbps", name=f"Test Case {case}", direction=direction, direction_source_label=src,
                                                traffic_mode="bidirectional", protocol=proto, statistic="average", **d)
                        else:
                            cc = summary.cell(rr, k)
                            if _num(cc.value) is not None:
                                out.measure(title, _ref(cc), cid, "throughput", cc.value, "Mbps", name=f"Test Case {case}", direction=label.lower(),
                                            direction_source_label={"DL": "Downlink", "UL": "Uplink"}[label], traffic_mode="unidirectional", protocol=proto, statistic="average", **d)
                if "latency" in rows and _num(summary.cell(rows["latency"], k).value) is not None:
                    out.measure(title, _ref(summary.cell(rows["latency"], k)), cid, "latency_rtt", summary.cell(rows["latency"], k).value, "ms", name=f"Test Case {case}",
                                statistic="average", **d)
            r = end
    perf = _sheet(wb, "4. Performance Test")
    if perf is None:
        return
    title = perf.title.strip()
    r = 1
    while r <= perf.max_row:
        m = re.match(r"^4\.\d+\s+Test Case\s*(\d+)", _t(perf.cell(r, 1).value))
        if not m:
            r += 1
            continue
        case = int(m.group(1))
        end = r + 1
        while end <= perf.max_row and not re.match(r"^4\.\d+\s+Test Case", _t(perf.cell(end, 1).value)):
            end += 1
        wan_row = next((x for x in range(r + 1, r + 5) if _t(perf.cell(x, 1).value) == "WAN Interface"), None)
        if wan_row is None:
            r = end
            continue
        d = _slot_dims(perf.cell(wan_row, 7).value, perf.cell(wan_row + 1, 7).value, perf.cell(wan_row + 1, 2).value)
        _flag_band(out, d, title, case)
        cid = _case_id(d)
        section = None
        for rr in range(wan_row + 2, end):
            a = _t(perf.cell(rr, 1).value)
            if a.startswith("TCP"):
                section = "tcp"
                continue
            if a.startswith("UDP Throughput"):
                section = "udp"
                continue
            if a.startswith("Latency"):
                section = "latency"
                continue
            if section == "tcp" and a in ("Downlink", "Uplink", "Bidirection - DL", "Bidirection - UL"):
                direction = "dl" if a.endswith(("Downlink", "DL")) else "ul"
                for col, stat, idx in ((2, "value", 1), (3, "value", 2), (4, "value", 3), (5, "peak", None)):
                    cell = perf.cell(rr, col)
                    if _num(cell.value) is not None:
                        out.measure(title, _ref(cell), cid, "throughput", cell.value, "Mbps", name=f"Test Case {case}", direction=direction, direction_source_label=a,
                                    traffic_mode="bidirectional" if a.startswith("Bidirection") else "unidirectional", protocol="tcp", statistic=stat, sample_index=idx, **d)
            elif section == "udp" and a in ("Downlink", "Uplink"):
                direction = "dl" if a == "Downlink" else "ul"
                res, lost = perf.cell(rr, 2), perf.cell(rr, 3)
                if _num(res.value) is not None:
                    out.measure(title, _ref(res), cid, "throughput", res.value, "Mbps", name=f"Test Case {case}", direction=direction, direction_source_label=a,
                                traffic_mode="unidirectional", protocol="udp", statistic="value", **d)
                if _num(lost.value) is not None:
                    out.measure(title, _ref(lost), cid, "udp_lost_ratio", lost.value, "unitless", name=f"Test Case {case}", direction=direction, direction_source_label=a,
                                protocol="udp", statistic="value", **d)
            elif section == "latency" and a.startswith("RTT"):
                for col, stat in ((2, "min"), (3, "average"), (4, "max")):
                    cell = perf.cell(rr, col)
                    if _num(cell.value) is not None and stat != "average":
                        out.measure(title, _ref(cell), cid, "latency_rtt", cell.value, "ms", name=f"Test Case {case}", statistic=stat, **d)
                for col, metric, unit in ((6, "rsrp", "dBm"), (7, "rsrq", "dB"), (8, "sinr", "dB")):
                    cell = perf.cell(rr, col)
                    if _num(cell.value) is not None:
                        out.measure(title, _ref(cell), cid, metric, cell.value, unit, name=f"Test Case {case}", statistic="value", **d)
        r = end


# ----------------------------------------------------------------------------- cellular NR handover (SIT-SR-SC-NR-Handover)
HANDOVER_MODES = (("4.1", "xn", "Xn Handover"), ("4.2", "ng", "NG Handover"))
# Configuration labels read from "2.7 Test Configuration": label -> (condition name, unit). A value is the next cell to the right that is not itself a label.
HANDOVER_CONFIG = {"Band": ("band", None), "RF Tx Power": ("rf_tx_power", None), "Center Frequency": ("center_frequency", None), "Bandwidth": ("bandwidth", "MHz"),
                   "ARFCN": ("arfcn", None), "UL Modulation": ("ul_modulation", None), "AbsArfcnSsb": ("abs_arfcn_ssb", None), "UL Dmrs-Add.Pos.": ("ul_dmrs_add_pos", None),
                   "UL MIMO Layer": ("ul_mimo_layer", None), "Time Slot": ("time_slot", None), "Cell ID": ("cell_id", None), "PCI": ("pci", None), "TAC": ("tac", None),
                   "AbsArfcn": ("abs_arfcn", None), "Neighbor IP": ("neighbor_ip", None)}


def _handover_peer(wb) -> dict:
    """Small Cell B in "2. Introduction": the model, firmware, hardware version, band and NPI stage (serial number and MAC addresses are deliberately not read)."""
    ws = _sheet(wb, "2. Introduction")
    peer: dict[str, Any] = {}
    if ws is None:
        return peer
    start = next((c.row for row in ws.iter_rows(max_row=40) for c in row if isinstance(c.value, str) and _t(c.value).startswith("Small Cell B")), None)
    if start is None:
        return peer
    keys = {"model name": "model", "firmware version": "fw_version", "hardware version": "hw_version", "band": "band", "npi stage": "npi_stage"}
    for r in range(start + 1, min(start + 10, ws.max_row + 1)):
        tokens = [(c.column, _t(c.value)) for c in ws[r] if c.value not in (None, "") and c.column <= 10]
        if not tokens:
            continue  # the block has blank lines (serial number and MAC rows are not read, and a row may be empty)
        if tokens[0][1] in ("Engineer", "Test Laboratory Location") or re.match(r"^\d\.\d", tokens[0][1]):
            break
        key = keys.get(tokens[0][1].rstrip("：: ").strip().lower())
        if key and len(tokens) > 1:
            peer[key] = " ".join(t for _, t in tokens[1:])
    return peer


def _handover_conditions(wb, out: Collector) -> dict:
    """Test configuration of both cells, the neighbour cells and the attenuator / SS-RSRP set points. Returns the dimensions of Small Cell A
    (band, bandwidth, centre frequency, time slot), which tag every handover measurement."""
    ws = _sheet(wb, "2.7")
    dims: dict[str, Any] = {"band": None, "bandwidth_mhz": None, "center_freq_mhz": None, "time_slot": None}
    if ws is None:
        return dims
    title = ws.title.strip()
    section = None
    for row in ws.iter_rows(max_col=10):
        a = _t(row[0].value)
        if a.startswith("Time slot"):
            break  # the list below is the template's catalogue of selectable time slots, not this report's configuration
        if section == "ue":  # the rows under "UE SS-RSRP" are named "Small Cell A / B" too; they are levels, not new cell sections
            _handover_ue_levels([c for c in row if c.value not in (None, "")], out, title)
            continue
        m = re.match(r"^Small Cell ([AB]):?$", a)
        if m:
            section = "cell_" + m.group(1).lower()
            continue
        if a == "Neighbor Cell" and section:
            section = section.split(".")[0] + ".neighbor"
            continue
        if a.startswith("UE SS-RSRP"):
            section = "ue"
            continue
        cells = [c for c in row if c.value not in (None, "")]
        if not section:
            continue
        for i, c in enumerate(cells):
            label = _t(c.value)
            if label not in HANDOVER_CONFIG:
                continue
            nxt = next((x for x in cells[i + 1:] if _t(x.value) not in HANDOVER_CONFIG), None)
            if nxt is None or (i + 1 < len(cells) and _t(cells[i + 1].value) in HANDOVER_CONFIG):
                continue
            name, unit = HANDOVER_CONFIG[label]
            full = f"{section}.{name}"
            if _num(nxt.value) is not None:
                out.conditions.append({"name": full, "value": float(nxt.value), "unit": unit, "source_sheet": title, "source_cell_range": _ref(nxt)})
            else:
                out.conditions.append({"name": full, "text": _t(nxt.value), "unit": unit, "source_sheet": title, "source_cell_range": _ref(nxt)})
            if section == "cell_a":
                if name == "band":
                    dims["band"] = _t(nxt.value)
                elif name == "bandwidth" and _num(nxt.value) is not None:
                    dims["bandwidth_mhz"] = int(nxt.value)
                elif name == "center_frequency" and _num(nxt.value) is not None:
                    dims["center_freq_mhz"] = int(round(float(nxt.value) * 1000))  # the cell holds GHz (4.85); the ARFCN in the same block agrees (723332 = 4849.98 MHz)
                elif name == "time_slot":
                    dims["time_slot"] = _t(nxt.value)
    return dims


def _handover_ue_levels(cells, out: Collector, title: str) -> None:
    """"Attenuator | 0 | | 25" and "Small Cell A | -60 | | -85": the near and far set points (the sheet's note says the first is Near and the second Far)."""
    if not cells:
        return
    label = _t(cells[0].value)
    values = [c for c in cells[1:] if _num(c.value) is not None]
    if label == "Attenuator":
        name, unit = "ue.attenuator", "dB"
    elif re.match(r"^Small Cell [AB]$", label):
        name, unit = f"ue.ss_rsrp_cell_{label[-1].lower()}", "dBm"
    else:
        return
    for pos, c in zip(("near", "far"), values):
        out.conditions.append({"name": f"{name}.{pos}", "value": float(c.value), "unit": unit, "source_sheet": title, "source_cell_range": _ref(c)})


def _handover_texts(wb, out: Collector) -> None:
    """Purpose, scope and procedure are prose in column B under their numbered heading."""
    for prefix, heading, kind in (("2. Introduction", "2.1", "Purpose"), ("2. Introduction", "2.2", "Scope"), ("2.5", "2.6", "Test Procedure")):
        ws = _sheet(wb, prefix)
        if ws is None:
            continue
        start = next((c.row for row in ws.iter_rows(max_col=2) for c in row[:1] if isinstance(c.value, str) and _t(c.value).startswith(heading)), None)
        if start is None:
            continue
        lines, first = [], None
        for r in range(start + 1, ws.max_row + 1):
            if re.match(r"^\d\.\d", _t(ws.cell(r, 1).value)):
                break
            cell = ws.cell(r, 2)
            if _t(cell.value):
                first = first or cell
                lines.append(_t(cell.value))
        if lines:
            out.text(ws.title.strip(), _ref(first), "section_text", " ".join(lines), f"{heading} {kind}")


def _handover(wb, out: Collector, dut: dict) -> None:
    """One row per handover ("Handover 2 / 10 / 100 times" blocks, numbered 1..n): latency and throughput before and after, success, ping loss and the
    signed variations the report prints. The summary sheet adds each block's verdict, success rate and maxima. The performance sheets repeat their
    header on every page, so a block header seen again continues the same block."""
    cfg = _handover_conditions(wb, out)
    _handover_texts(wb, out)
    dims = {k: v for k, v in cfg.items() if v is not None}
    for prefix, mode, label in HANDOVER_MODES:
        ws = _sheet(wb, prefix)
        if ws is None:
            continue
        title = ws.title.strip()
        group = None
        cols: dict[str, int] = {}
        for row in ws.iter_rows(max_col=13):
            a = row[0].value
            text = _t(a)
            m = re.match(r"^Handover\s+(\d+)\s+times", text)
            if m:
                group = int(m.group(1))
                continue
            if text == "No":
                labels = {_t(c.value): c.column for c in row if isinstance(c.value, str)}
                cols.update({"lat": labels.get("Average Latency", cols.get("lat", 2)), "tput": labels.get("Average Throughput", cols.get("tput", 4)),
                             "ok": labels.get("Handover Success", cols.get("ok", 6)), "loss": labels.get("Ping Loss Count", cols.get("loss", 7))})
                continue
            if _t(row[1].value) == "Before" and "Variation" in {_t(c.value) for c in row}:
                var = next(c.column for c in row if _t(c.value) == "Variation")
                cols["var_lat"], cols["var_tput"] = var + 1, var + 2  # "Variation | Latency | Tput" (signed), then the same two as absolute values
                continue
            if group is None or not isinstance(a, (int, float)) or isinstance(a, bool) or not cols or _num(row[cols["lat"] - 1].value) is None:
                continue
            no = int(a)
            cid = f"cellular_handover:{mode}:{group}"
            name = f"{label} {group} times"
            common = dict(name=name, sample_index=no, **dims)

            def cell(key):
                return row[cols[key] - 1] if key in cols and cols[key] - 1 < len(row) else None
            for key, metric, unit, extra in (("lat", "latency_rtt_before_ho", "ms", {}), ("tput", "throughput_before_ho", "Mbps", {"direction": "dl"})):
                c = cell(key)
                if c is not None and _num(c.value) is not None:
                    out.measure(title, _ref(c), cid, metric, c.value, unit, statistic="average", **extra, **common)
            for key, metric, unit, extra in (("lat", "latency_rtt_after_ho", "ms", {}), ("tput", "throughput_after_ho", "Mbps", {"direction": "dl"})):
                c = row[cols[key]] if cols[key] < len(row) else None  # "After" is the column right of "Before"
                if c is not None and _num(c.value) is not None:
                    out.measure(title, _ref(c), cid, metric, c.value, unit, statistic="average", **extra, **common)
            ok = cell("ok")
            if ok is not None and _t(ok.value).lower() in ("yes", "no"):
                out.measure(title, _ref(ok), cid, "ho_success", 1 if _t(ok.value).lower() == "yes" else 0, "count", **common)
            loss = cell("loss")
            if loss is not None and _num(loss.value) is not None:
                out.measure(title, _ref(loss), cid, "ping_loss_count", loss.value, "count", **common)
            for key, metric, unit, extra in (("var_lat", "latency_variation", "ms", {}), ("var_tput", "throughput_variation", "Mbps", {"direction": "dl"})):
                c = cell(key)
                if c is not None and _num(c.value) is not None:
                    out.measure(title, _ref(c), cid, metric, c.value, unit, basis="reported_derived", **extra, **common)
    _handover_summary(wb, out, dims)


def _handover_summary(wb, out: Collector, dims: dict) -> None:
    """"3.1 Xn Handover Test Summary" / "3.2 NG ...": a header row ("Latency Test | Round trip | 10 times | 100 times") and the rows below it. Columns after I are
    the template's Example and are ignored."""
    ws = _sheet(wb, "3. Test Result Summary")
    if ws is None:
        return
    title = ws.title.strip()
    mode, groups = None, {}
    wanted = {"HO Success Rate": ("ho_success_rate", "ratio", None), "Max. Tput Variation": ("max_throughput_variation", "Mbps", "max"),
              "Max. Latency Variation": ("max_latency_variation", "ms", "max"), "Max. Ping Loss Count": ("max_ping_loss_count", "count", "max")}
    for row in ws.iter_rows(max_col=9):
        a = _t(row[0].value)
        m = re.match(r"^3\.\d\s+(Xn|NG)\s+Handover", a)
        if m:
            mode, groups = m.group(1).lower(), {}
            continue
        if a == "Latency Test":
            groups = {}
            for c in row[1:]:
                t = _t(c.value)
                if t == "Round trip":
                    groups[c.column] = 2  # one round trip is the 2-handover block (A to B and back)
                elif re.match(r"^\d+\s+times$", t):
                    groups[c.column] = int(t.split()[0])
            continue
        if not mode or not groups:
            continue
        for col, group in groups.items():
            c = row[col - 1]
            cid = f"cellular_handover:{mode}:{group}"
            if a == "Test Result" and _t(c.value):
                out.result(title, _ref(c), cid, "Latency Test", c.value)
            elif a in wanted and _num(c.value) is not None:
                metric, unit, stat = wanted[a]
                extra = {"statistic": stat} if stat else {}
                out.measure(title, _ref(c), cid, metric, c.value, unit, name=f"{'Xn' if mode == 'xn' else 'NG'} Handover {group} times", basis="reported_derived", **extra, **dims)
