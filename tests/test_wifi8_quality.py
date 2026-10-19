import importlib.util
import json
import logging
from pathlib import Path

from src.wifi8.quality import (QUALITY_LOG_PREFIX, agent_metrics, judge, overall_status, parse_quality_lines,
                               retrieval_metrics, summarize_trust)

THRESHOLDS = {
    "retrieval.hit_at_10": {"direction": "higher", "warn": 0.9, "fail": 0.8, "regression": 0.07},
    "retrieval.ms_p50": {"direction": "lower", "warn": 1000, "fail": 3000},
    "trust.values_not_found_rate": {"direction": "lower", "warn": 0.05, "fail": 0.10},
}


def record(not_found=0, values=10, claims=10, cited=8, tool=1, wfa=1, total=2, stop="answered", error=False, ms=8000):
    return {"stop_reason": stop, "elapsed_ms": ms, "grounding_error": error,
            "grounding": {"claims": claims, "claims_cited": cited, "claims_tool_data": tool, "values": values,
                          "values_not_found": not_found},
            "sources": {"total": total, "wfa": wfa, "current": total}}


def test_parse_quality_lines_ignores_other_and_malformed_lines():
    lines = ["[2026-10-17 04:47:25,299: INFO/ForkPoolWorker-1] " + QUALITY_LOG_PREFIX + json.dumps(record()),
             "[2026-10-17 04:47:25,300: INFO/MainProcess] Task succeeded",
             QUALITY_LOG_PREFIX + "{not json", QUALITY_LOG_PREFIX + "[1, 2]"]
    assert len(parse_quality_lines(lines)) == 1


def test_summarize_trust_rates():
    records = [record(), record(not_found=2, claims=10, cited=5, tool=0), record(stop="max_steps", error=True, ms=20000),
               {"stop_reason": "answered", "elapsed_ms": 5000, "grounding": None}]
    s = summarize_trust(records)
    assert s["answers"] == 4 and s["graded_answers"] == 3
    assert s["values_not_found_rate"] == round(2 / 30, 4)
    assert s["answers_with_value_not_found_rate"] == round(1 / 3, 4)
    assert s["unsupported_claim_rate"] == round((30 - (8 + 1) * 2 - 5) / 30, 4)
    assert s["wfa_source_share"] == 0.5 and s["grounding_error_rate"] == 0.25 and s["not_answered_rate"] == 0.25
    assert s["stop_reasons"] == {"answered": 3, "max_steps": 1} and s["latency_ms_p50"] in (8000, 5000)
    assert summarize_trust([])["values_not_found_rate"] is None
    assert s["answers_with_cited_mismatch_rate"] == 0
    mismatched = [record(), record()]
    mismatched[0]["grounding"]["values_not_in_cited"] = 3
    mismatched[1]["grounding"]["claims_source_mismatch"] = 1
    assert summarize_trust(mismatched + [record(), record()])["answers_with_cited_mismatch_rate"] == 0.5


def test_judge_thresholds_regression_and_missing_values():
    checks = {c["metric"]: c for c in judge("retrieval", {"hit_at_10": 0.95, "ms_p50": 1500}, THRESHOLDS, {"hit_at_10": 0.933})}
    assert checks["retrieval.hit_at_10"]["status"] == "PASS" and checks["retrieval.ms_p50"]["status"] == "WARN"
    dropped = judge("retrieval", {"hit_at_10": 0.91, "ms_p50": 100}, THRESHOLDS, {"hit_at_10": 1.0})
    assert dropped[0]["status"] == "WARN" and "比上次變差" in dropped[0]["reason"]  # above the threshold but a big drop
    assert judge("retrieval", {"hit_at_10": 0.7, "ms_p50": 100}, THRESHOLDS)[0]["status"] == "FAIL"
    assert judge("trust", {"values_not_found_rate": None}, THRESHOLDS)[0]["status"] == "INSUFFICIENT"
    assert overall_status([{"status": "PASS"}, {"status": "WARN"}]) == "WARN"
    assert overall_status([{"status": "INSUFFICIENT"}]) == "PASS" and overall_status([{"status": "FAIL"}, {"status": "WARN"}]) == "FAIL"


def test_eval_summaries_map_to_metrics():
    summary = {"overall": {"retrieval_hit_at_k": 0.933, "retrieval_mrr": 0.79, "retrieval_ms_p50": 90, "answer_pass": 0.97,
                           "fact_coverage": 0.96, "cited_gold": 1.0, "latency_ms_p50": 8000, "errors": 1, "cases": 34}}
    assert retrieval_metrics(summary) == {"hit_at_10": 0.933, "mrr": 0.79, "figure_hit_at_10": None, "ms_p50": 90, "cases": 34}
    assert agent_metrics(summary)["answer_pass"] == 0.97 and agent_metrics(summary)["errors"] == 1
    summary["overall"].update({"retrieval_figure_hit_at_k": 0.889, "cited_figure": 0.778, "unnumbered_repeat_answers": 0})
    assert retrieval_metrics(summary)["figure_hit_at_10"] == 0.889
    assert agent_metrics(summary)["cited_figure"] == 0.778 and agent_metrics(summary)["unnumbered_repeat_answers"] == 0


def test_agent_logs_counts_only_and_can_be_disabled(caplog, monkeypatch):
    from types import SimpleNamespace
    from src.wifi8.agent import log_quality, quality_record
    result = {"answer": "機密問題的回答內容 [S1]", "citations": [{"ref": "S1"}], "trace": [{}], "stop_reason": "answered", "elapsed_ms": 1200,
              "grounding": {"summary": {"claims": 1, "claims_cited": 1, "values": 0, "sources": {"total": 1, "wfa": 1, "current": 1}}}}
    tools = SimpleNamespace(search_engine=SimpleNamespace(package_id="pkg"))
    with caplog.at_level(logging.INFO, logger="km.wifi8.quality"):
        log_quality(result, tools)
    line = caplog.records[-1].getMessage()
    parsed = parse_quality_lines([line])[0]
    assert parsed["package_id"] == "pkg" and parsed["grounding"]["claims"] == 1 and parsed["citations"] == 1
    assert "機密" not in line and "answer" not in parsed  # never the question or answer text
    assert quality_record({"answer": "x"})["grounding"] is None
    caplog.clear()
    monkeypatch.setenv("KM_WIFI8_QUALITY_LOG", "0")
    log_quality(result, tools)
    assert not caplog.records


def test_report_rendering():
    spec = importlib.util.spec_from_file_location("wifi8_quality_check", Path(__file__).resolve().parent.parent / "scripts" / "wifi8_quality_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks = judge("retrieval", {"hit_at_10": 0.95, "ms_p50": 90}, THRESHOLDS)
    text = module.render({"created_utc": "t", "commit": "abc", "status": "PASS", "trust_window_hours": 24, "levels": ["retrieval"],
                          "zones": {"da40": {"_status": "PASS", "retrieval": {"status": "PASS", "metrics": {}, "checks": checks,
                                                                             "package_id": "pkg", "failed_cases": ["T01"]}}}})
    assert "## DA40（PASS）" in text and "① 檢索找文件的能力：PASS" in text and "| retrieval.hit_at_10 | 95.0% |" in text
    assert "檢索前 10 筆沒有標準來源的題目：T01" in text


def test_report_formats_rates_scores_and_counts():
    spec = importlib.util.spec_from_file_location("wifi8_quality_check", Path(__file__).resolve().parent.parent / "scripts" / "wifi8_quality_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.fmt(0.7944, "retrieval.mrr") == "0.794"
    assert module.fmt(0.933, "retrieval.hit_at_10") == "93.3%" and module.fmt(0.014, "trust.values_not_found_rate") == "1.4%"
    assert module.fmt(7070, "agent.latency_ms_p50") == "7,070" and module.fmt(1, "agent.errors") == "1" and module.fmt(None) == "—"


def test_previous_run_is_compared_only_with_the_same_golden_set(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("wifi8_quality_check", Path(__file__).resolve().parent.parent / "scripts" / "wifi8_quality_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    rows = [{"zone": "da40", "level": "retrieval", "status": "PASS", "metrics": {"hit_at_10": 0.93}},  # before digests were recorded
            {"zone": "da40", "level": "retrieval", "status": "PASS", "metrics": {"hit_at_10": 0.91}, "cases_sha256": "new"}]
    (tmp_path / "history.jsonl").write_text(json.dumps(rows[0]) + "\n", encoding="utf-8")
    assert module.previous_metrics("da40", "retrieval", "new") is None
    assert module.previous_metrics("da40", "retrieval") == {"hit_at_10": 0.93}  # trust is not tied to the golden set
    (tmp_path / "history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert module.previous_metrics("da40", "retrieval", "new") == {"hit_at_10": 0.91}
    assert len(module.cases_digest()) == 16
    checks = judge("agent", {"unnumbered_repeat_answers": 1}, {"agent.unnumbered_repeat_answers": {"direction": "lower", "warn": 0, "fail": 1}})
    assert checks[0]["status"] == "WARN"
    text = module.render({"created_utc": "t", "commit": "abc", "status": "WARN", "trust_window_hours": 24, "levels": ["agent"],
                          "zones": {"test": {"_status": "WARN", "agent": {"status": "WARN", "metrics": {}, "checks": checks,
                                                                         "figure_failed": ["F02"], "previous_note": "題庫和上次不同，這次不與上次比較是否退步。"}}}})
    assert "回答沒有引用標準圖片、或同一位置引用沒有標出第幾段的題目：F02" in text and "題庫和上次不同" in text
