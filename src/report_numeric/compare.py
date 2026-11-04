"""Deterministic comparison of two or more test runs (the evidence base of the RCA feature).

Everything here is computed by code from km_test rows: alignment, deltas, changed factors, Pass/Fail changes, quality flags. Each finding carries an
evidence id (F# factor, D# measurement, R# result, C# criteria, Q# quality) and the source sheet/cell it came from, so a later narrative step
(LLM or human) can cite it and a checker can verify every number it quotes. Nothing here guesses a cause or says better/worse unless the metric
dictionary defines higher_is_better; an undefined direction is reported as "changed".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import query as q

MAX_RUNS = 6
# Dimensions that identify "the same measurement" across runs. value_basis is part of the key: a reported total is never aligned with a measured value.
KEY_DIMS = ("test_case_id", "metric_name", "direction", "band", "bandwidth_mhz", "channel", "attenuation_db", "angle_deg", "traffic_mode", "protocol",
            "statistic", "sample_index", "wireless_mode", "time_slot", "value_basis")
FACTOR_FIELDS = ("firmware_version", "hardware_version", "chipset_vendor", "ethernet_type", "npi_stage", "test_date", "report_type", "technology", "dut_model",
                 "report_revision", "document_version")


class CompareError(ValueError):
    """Bad selection (unknown run, too few or too many, different report types): reported back to the caller, never guessed around."""


@dataclass(frozen=True)
class Thresholds:
    """When a difference counts as notable. These defaults are engineering placeholders until CSIT defines them per metric."""
    pct: float = 5.0
    per_metric: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "rssi": {"abs": 3.0}, "latency_rtt": {"pct": 10.0}, "pass_rate": {"abs": 0.05},
        "pass_count": {"abs": 1.0}, "fail_count": {"abs": 1.0}, "total_count": {"abs": 1.0}})

    def notable(self, metric: str, base: float, value: float) -> bool:
        rule = self.per_metric.get(metric, {})
        delta = value - base
        if "abs" in rule and abs(delta) >= rule["abs"]:
            return True
        pct = rule.get("pct", self.pct) if "abs" not in rule else None
        if pct is not None and base != 0 and abs(delta) / abs(base) * 100 >= pct:
            return True
        return pct is not None and base == 0 and delta != 0


def _rows(conn, sql: str, params: dict) -> list[dict]:
    cur = conn.execute(sql, params)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def load_runs(conn, run_ids: list[str], roles=q.DEFAULT_ROLES) -> list[dict]:
    """Read-only, role-filtered. Returns the runs in the order requested; an unknown or not permitted id is an error, not a silent skip."""
    ids = list(dict.fromkeys(str(r) for r in run_ids))
    if len(ids) < 2:
        raise CompareError("比較至少需要 2 份報告")
    if len(ids) > MAX_RUNS:
        raise CompareError(f"一次最多比較 {MAX_RUNS} 份報告")
    runs = _rows(conn, """SELECT test_run_id, product_id, dut_model, report_type, technology, document_id, document_version, report_revision, npi_stage, firmware_version,
                                 hardware_version, chipset_vendor, ethernet_type, test_date, overall_result, quality_status, formula_error_count, approval_basis
                          FROM km_test.test_run WHERE test_run_id = ANY(%(ids)s) AND access_roles && %(roles)s AND publish_status = 'published'""",
                 {"ids": ids, "roles": list(roles)})
    by_id = {r["test_run_id"]: r for r in runs}
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise CompareError("找不到或無權限讀取報告：" + "、".join(missing))
    out = []
    for i in ids:
        r = dict(by_id[i])
        r["test_date"] = r["test_date"].isoformat() if r["test_date"] is not None else None
        quality = conn.execute("SELECT quality FROM km_test.report_package WHERE test_run_id = %(r)s", {"r": i}).fetchone()
        r["error_summary"] = error_summary(quality[0] if quality else None)
        r["measurements"] = _rows(conn, """SELECT test_case_id, test_case_name, metric_name, value, unit, value_basis, band, bandwidth_mhz, channel, direction, attenuation_db,
                                                  angle_deg, traffic_mode, protocol, statistic, sample_index, wireless_mode, time_slot, source_sheet, source_cell_range
                                           FROM km_test.test_measurement WHERE test_run_id = %(r)s""", {"r": i})
        r["results"] = _rows(conn, """SELECT test_case_id, item_label, band, bandwidth_mhz, channel, criteria_value, criteria_unit, result, source_sheet, source_cell_range
                                      FROM km_test.test_item_result WHERE test_run_id = %(r)s""", {"r": i})
        r["criteria"] = _rows(conn, """SELECT band, bandwidth_mhz, spatial_stream, wireless_mode, attenuation_range, reference_rate_mbps, criteria_value, criteria_unit,
                                              source_sheet, source_cell_range FROM km_test.criteria_reference WHERE test_run_id = %(r)s""", {"r": i})
        r["conditions"] = _rows(conn, """SELECT name, value, text_value, unit, band, bandwidth_mhz, source_sheet, source_cell_range
                                         FROM km_test.test_condition WHERE test_run_id = %(r)s""", {"r": i})
        out.append(r)
    return out


def error_summary(quality: Any) -> list[dict]:
    """Where a report's formula-error cells are, grouped by sheet: {sheet, hidden, count, values, cells(first 4)}.
    Error cells are never stored as numbers (the importer keeps the report and flags it), so this only tells a reader what was missing at the source."""
    errors = (quality or {}).get("formula_errors", []) if isinstance(quality, dict) else []
    groups: dict[tuple, dict] = {}
    for e in errors:
        g = groups.setdefault((e.get("sheet"), e.get("sheet_state")), {"sheet": e.get("sheet"), "hidden": e.get("sheet_state") not in (None, "visible"), "count": 0, "values": set(), "cells": []})
        g["count"] += 1
        g["values"].add(str(e.get("value")))
        if len(g["cells"]) < 4:
            g["cells"].append(e.get("cell"))
    return [{**g, "values": sorted(g["values"])} for g in sorted(groups.values(), key=lambda x: (x["hidden"], str(x["sheet"])))]


def load_directions(conn) -> dict[str, bool | None]:
    """metric -> higher_is_better (None = undefined, so no better/worse wording)."""
    try:
        return {r["metric_name"]: r["higher_is_better"] for r in _rows(conn, "SELECT metric_name, higher_is_better FROM km_test.metric_dictionary", {})}
    except Exception:  # noqa: BLE001 - an older schema without the column: every direction stays undefined
        return {}


def _key(row: dict, dims: tuple[str, ...]) -> tuple:
    return tuple(row.get(d) for d in dims)


def _label(row: dict) -> str:
    metric = row.get("metric_name")
    if metric and str(metric).lower() == str(row.get("test_case_id") or "").lower():
        metric = None  # "Throughput throughput ..." reads as a stutter
    parts = [row.get("test_case_id"), metric, row.get("direction"), row.get("band"),
             f"{row['bandwidth_mhz']}MHz" if row.get("bandwidth_mhz") else None, f"ch{row['channel']}" if row.get("channel") is not None else None,
             f"{row['attenuation_db']}dB" if row.get("attenuation_db") is not None else None, f"{row['angle_deg']}°" if row.get("angle_deg") is not None else None,
             row.get("protocol"), row.get("statistic")]
    return " ".join(str(p) for p in parts if p)


def _cell(m: dict) -> str:
    return f"{m['source_sheet']}!{m['source_cell_range']}"


def _assess(metric: str, base: float, value: float, directions: dict[str, bool | None], notable: bool) -> str:
    if not notable:
        return "unchanged"
    better = directions.get(metric)
    if better is None:
        return "changed"  # direction undefined: describe the difference only
    return "improvement" if (value > base) == bool(better) else "regression"


def compare_runs(runs: list[dict], directions: dict[str, bool | None] | None = None, thresholds: Thresholds | None = None, top: int = 40) -> dict:
    """runs[0] is the baseline. Returns the evidence pack described in the module docstring."""
    if not 2 <= len(runs) <= MAX_RUNS:
        raise CompareError(f"需要 2 到 {MAX_RUNS} 份報告")
    types = {r["report_type"] for r in runs}
    if len(types) > 1:
        # Throughput and RvR (or cellular) are different experiments: aligning them would manufacture differences.
        raise CompareError("報告類型不同，不可直接比較：" + "、".join(sorted(types)))
    directions, thresholds = directions or {}, thresholds or Thresholds()
    base, n = runs[0], len(runs)
    evidence: dict[str, dict] = {}

    def add(prefix: str, payload: dict) -> str:
        eid = f"{prefix}{sum(1 for k in evidence if k.startswith(prefix)) + 1}"
        evidence[eid] = {"id": eid, **payload}
        return eid

    run_info = [{"index": i, "test_run_id": r["test_run_id"], "product_id": r["product_id"], "dut_model": r["dut_model"], "document_id": r["document_id"],
                 **{f: r.get(f) for f in FACTOR_FIELDS}, "overall_result": r["overall_result"], "quality_status": r["quality_status"],
                 "formula_error_count": r.get("formula_error_count", 0), "error_summary": r.get("error_summary", [])} for i, r in enumerate(runs)]

    # ---- changed factors (what is different between the runs, before looking at any number) ----
    factors = []
    for f in FACTOR_FIELDS:
        values = [r.get(f) for r in runs]
        if len({str(v) for v in values}) > 1:
            factors.append({"id": add("F", {"kind": "factor", "factor": f, "values": values}), "factor": f, "values": values})
    names = sorted({(c["name"], c["band"], c["bandwidth_mhz"]) for r in runs for c in r["conditions"]}, key=lambda t: tuple("" if x is None else str(x) for x in t))
    for name, band, bw in names:
        per_run = []
        for r in runs:
            c = next((c for c in r["conditions"] if (c["name"], c["band"], c["bandwidth_mhz"]) == (name, band, bw)), None)
            per_run.append(None if c is None else (c["value"] if c["value"] is not None else c["text_value"]))
        if len({str(v) for v in per_run}) > 1:
            label = f"條件 {name}" + (f" {band}" if band else "") + (f" {bw}MHz" if bw else "")
            factors.append({"id": add("F", {"kind": "condition", "factor": label, "values": per_run}), "factor": label, "values": per_run})
    # Several factors changing together cannot be separated by this data: say so instead of letting a story pick one.
    confounded = len([f for f in factors if f["factor"] in ("firmware_version", "hardware_version", "chipset_vendor", "ethernet_type")]) > 1

    # ---- aligned measurements ----
    tables = []
    for r in runs:
        index: dict[tuple, dict] = {}
        dup = 0
        for m in r["measurements"]:
            k = _key(m, KEY_DIMS)
            if k in index:
                dup += 1
            index[k] = m
        tables.append((index, dup))
    all_keys = sorted({k for t, _ in tables for k in t}, key=lambda k: tuple("" if x is None else str(x) for x in k))
    diffs, only_some, unchanged = [], [], 0
    for k in all_keys:
        row = {d: v for d, v in zip(KEY_DIMS, k)}
        cells = [t.get(k) for t, _ in tables]
        present = [c for c in cells if c is not None]
        if len(present) < n:
            eid = add("D", {"kind": "coverage", "label": _label(row), "present_in": [i for i, c in enumerate(cells) if c is not None]})
            only_some.append({"id": eid, "label": _label(row), "present_in": [i for i, c in enumerate(cells) if c is not None]})
            continue
        units = {c["unit"] for c in present}
        if len(units) > 1:
            eid = add("D", {"kind": "unit_mismatch", "label": _label(row), "units": sorted(units)})
            only_some.append({"id": eid, "label": _label(row), "unit_mismatch": sorted(units)})
            continue
        b = cells[0]["value"]
        per_run = []
        worst = None
        for i, c in enumerate(cells):
            v = c["value"]
            delta = v - b if i else 0.0
            pct = (delta / abs(b) * 100) if (i and b != 0) else None
            notable = bool(i) and thresholds.notable(row["metric_name"], b, v)
            assess = "baseline" if i == 0 else _assess(row["metric_name"], b, v, directions, notable)
            per_run.append({"run": i, "value": v, "delta": delta if i else None, "delta_pct": pct, "assessment": assess, "source": _cell(c)})
            if notable and (worst is None or abs(pct if pct is not None else delta) > worst):
                worst = abs(pct if pct is not None else delta)
        if worst is None:
            unchanged += 1
            continue
        eid = add("D", {"kind": "measurement", "label": _label(row), "metric": row["metric_name"], "unit": cells[0]["unit"], "per_run": per_run})
        diffs.append({"id": eid, "label": _label(row), "key": row, "metric": row["metric_name"], "unit": cells[0]["unit"], "per_run": per_run, "magnitude": worst,
                      "worst_assessment": next((p["assessment"] for p in per_run if p["assessment"] == "regression"), None)
                      or next((p["assessment"] for p in per_run if p["assessment"] == "changed"), "improvement")})
    diffs.sort(key=lambda d: -d["magnitude"])

    # ---- Pass/Fail changes ----
    res_idx = [{(x["test_case_id"], x["item_label"]): x for x in r["results"]} for r in runs]
    result_changes = []
    for k in sorted({k for t in res_idx for k in t}):
        cells = [t.get(k) for t in res_idx]
        outcomes = [c["result"] if c else None for c in cells]
        if len(set(outcomes)) > 1:
            eid = add("R", {"kind": "result", "label": f"{k[0]} / {k[1]}", "outcomes": outcomes})
            result_changes.append({"id": eid, "label": f"{k[0]} / {k[1]}", "outcomes": outcomes,
                                   "sources": [_cell(c) if c else None for c in cells]})

    # ---- criteria (the pass line itself moved) ----
    def ckey(c):
        return (c["band"], c["bandwidth_mhz"], c["spatial_stream"], c["wireless_mode"], c["attenuation_range"])
    crit_idx = [{ckey(c): c for c in r["criteria"]} for r in runs]
    criteria_changes = []
    for k in sorted({k for t in crit_idx for k in t}, key=lambda t: tuple("" if x is None else str(x) for x in t)):
        vals = [t[k]["criteria_value"] if k in t else None for t in crit_idx]
        refs = [t[k]["reference_rate_mbps"] if k in t else None for t in crit_idx]
        if len(set(vals)) > 1 or len(set(refs)) > 1:
            label = " ".join(str(x) for x in k if x is not None)
            eid = add("C", {"kind": "criteria", "label": label, "criteria": vals, "reference_rate_mbps": refs})
            criteria_changes.append({"id": eid, "label": label, "criteria": vals, "reference_rate_mbps": refs})

    # ---- data quality ----
    quality = []
    for i, r in enumerate(runs):
        if r["quality_status"] != "clean" or r["formula_error_count"]:
            quality.append({"id": add("Q", {"kind": "quality", "run": i, "status": r["quality_status"], "formula_errors": r["formula_error_count"]}),
                            "run": i, "status": r["quality_status"], "formula_errors": r["formula_error_count"]})
        if tables[i][1]:
            quality.append({"id": add("Q", {"kind": "duplicate_keys", "run": i, "count": tables[i][1]}), "run": i, "duplicate_keys": tables[i][1]})

    counts = {"aligned": len(all_keys) - len(only_some), "notable": len(diffs), "unchanged": unchanged, "coverage_gaps": len(only_some),
              "regression": sum(1 for d in diffs if d["worst_assessment"] == "regression"),
              "changed_direction_undefined": sum(1 for d in diffs if d["worst_assessment"] == "changed")}
    return {"baseline": 0, "runs": run_info, "factors": factors, "confounded": confounded,
            "confounded_note": "韌體、硬體、晶片或乙太網路類型同時有變動，這份資料無法把差異歸因到單一因素。" if confounded else None,
            "counts": counts, "diffs": diffs[:top], "diffs_total": len(diffs), "coverage": only_some[:top], "result_changes": result_changes[:top],
            "criteria_changes": criteria_changes[:top], "quality": quality, "evidence": evidence,
            "thresholds": {"pct": thresholds.pct, "per_metric": thresholds.per_metric},
            "directions_defined": sorted(m for m, v in directions.items() if v is not None),
            "note": "higher_is_better 未定義的指標只標示『changed』，不判斷好壞。"}
