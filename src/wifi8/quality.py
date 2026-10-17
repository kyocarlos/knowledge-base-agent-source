"""Automated quality checks of the WiFi zone at three levels (used by scripts/wifi8_quality_check.py).

1. retrieval -- can search find the right documents?  (golden set, retrieval only: hit@10, MRR, latency)
2. agent     -- does the agent answer correctly?       (golden set, full agent: pass rate, facts, citations)
3. trust     -- can individual real answers be trusted? (per-answer grounding statistics logged by the
                worker for real user questions: values not found, uncited claims, WFA sources)

Each metric is judged against configured thresholds (PASS / WARN / FAIL) and against the previous run
of the same zone (a drop larger than the configured regression tolerance is at least WARN).
"""
from __future__ import annotations

import json
from typing import Any, Iterable

QUALITY_LOG_PREFIX = "WIFI8_ANSWER_QUALITY "
ORDER = {"PASS": 0, "INSUFFICIENT": 0, "WARN": 1, "FAIL": 2}


# ---- level 3: per-answer records -------------------------------------------------
def parse_quality_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Records from worker log lines (other lines and malformed records are ignored)."""
    records = []
    for line in lines:
        index = line.find(QUALITY_LOG_PREFIX)
        if index < 0:
            continue
        try:
            record = json.loads(line[index + len(QUALITY_LOG_PREFIX):].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _percentile(values: list[float], q: float) -> float | None:
    values = sorted(v for v in values if v is not None)
    return values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))] if values else None


def summarize_trust(records: list[dict[str, Any]]) -> dict[str, Any]:
    graded = [r for r in records if r.get("grounding")]
    g = lambda key: sum(r["grounding"].get(key, 0) for r in graded)  # noqa: E731
    claims, values = g("claims"), g("values")
    supported = g("claims_cited") + g("claims_tool_data")
    sources = [r.get("sources") or {} for r in graded]
    stop = {}
    for r in records:
        stop[r.get("stop_reason") or "unknown"] = stop.get(r.get("stop_reason") or "unknown", 0) + 1
    return {
        "answers": len(records),
        "graded_answers": len(graded),
        "grounding_error_rate": _ratio(sum(1 for r in records if r.get("grounding_error")), len(records)),
        "values_not_found_rate": _ratio(g("values_not_found"), values),
        "answers_with_value_not_found_rate": _ratio(sum(1 for r in graded if r["grounding"].get("values_not_found")), len(graded)),
        "unsupported_claim_rate": _ratio(claims - supported, claims),
        "wfa_source_share": _ratio(sum(s.get("wfa", 0) for s in sources), sum(s.get("total", 0) for s in sources)),
        "current_source_share": _ratio(sum(s.get("current", 0) for s in sources), sum(s.get("total", 0) for s in sources)),
        "not_answered_rate": _ratio(sum(1 for r in records if r.get("stop_reason") != "answered"), len(records)),
        "latency_ms_p50": _percentile([r.get("elapsed_ms") for r in records], 0.5),
        "latency_ms_p95": _percentile([r.get("elapsed_ms") for r in records], 0.95),
        "stop_reasons": stop,
        "totals": {"claims": claims, "values": values, "values_not_found": g("values_not_found")},
    }


# ---- levels 1 and 2: golden-set evaluation summaries ------------------------------
def retrieval_metrics(eval_summary: dict[str, Any]) -> dict[str, Any]:
    overall = eval_summary.get("overall") or {}
    return {"hit_at_10": overall.get("retrieval_hit_at_k"), "mrr": overall.get("retrieval_mrr"),
            "ms_p50": overall.get("retrieval_ms_p50"), "cases": overall.get("cases")}


def agent_metrics(eval_summary: dict[str, Any]) -> dict[str, Any]:
    overall = eval_summary.get("overall") or {}
    return {"answer_pass": overall.get("answer_pass"), "fact_coverage": overall.get("fact_coverage"),
            "cited_gold": overall.get("cited_gold"), "latency_ms_p50": overall.get("latency_ms_p50"),
            "errors": overall.get("errors"), "cases": overall.get("cases")}


# ---- judgement -----------------------------------------------------------------------
def judge(level: str, metrics: dict[str, Any], thresholds: dict[str, dict[str, Any]],
          previous: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """One check per configured metric of the level: status from thresholds, worsened against previous."""
    checks = []
    for name, rule in thresholds.items():
        if not name.startswith(level + "."):
            continue
        key = name.split(".", 1)[1]
        value = metrics.get(key)
        higher = rule.get("direction", "higher") == "higher"
        check = {"metric": name, "value": value, "direction": "higher" if higher else "lower",
                 "warn": rule.get("warn"), "fail": rule.get("fail"), "previous": (previous or {}).get(key)}
        if value is None:
            check["status"], check["reason"] = "INSUFFICIENT", "沒有資料"
            checks.append(check)
            continue
        worse = (lambda a, b: a < b) if higher else (lambda a, b: a > b)
        if rule.get("fail") is not None and worse(value, rule["fail"]):
            check["status"], check["reason"] = "FAIL", "超過失敗門檻"
        elif rule.get("warn") is not None and worse(value, rule["warn"]):
            check["status"], check["reason"] = "WARN", "超過警示門檻"
        else:
            check["status"], check["reason"] = "PASS", ""
        prev = check["previous"]
        tolerance = rule.get("regression")
        if prev is not None and tolerance is not None:
            drop = (prev - value) if higher else (value - prev)
            check["change"] = round(value - prev, 4)
            if drop > tolerance and check["status"] == "PASS":
                check["status"], check["reason"] = "WARN", f"比上次變差 {round(drop, 4)}（容許 {tolerance}）"
        checks.append(check)
    return checks


def overall_status(checks: list[dict[str, Any]]) -> str:
    worst = max((ORDER[c["status"]] for c in checks), default=0)
    return {0: "PASS", 1: "WARN", 2: "FAIL"}[worst]
