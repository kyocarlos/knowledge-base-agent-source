"""Test-report numbers in the zone's answers: the plan is checked, the database computes, the answer cites the result."""
import json

import pytest

from src.report_numeric import query as q
from src.zone_pages import stats
from src.zone_pages.agent import ZoneAgent

ROW = {"product_id": "SCU2050", "dut_model": "SCU2050", "document_id": "SIT-SR-SC-NR-Handover-SCU2050-EV-V004", "test_case_id": "cellular_handover:xn:100",
       "test_case_name": "Xn Handover 100 times", "metric_name": "latency_rtt_after_ho", "unit": "ms", "n": 21, "total": 700.0, "average": 33.3333, "minimum": 26.0,
       "maximum": 49.0, "median": 31.0, "p95": 45.0, "first_no": 40, "last_no": 60}
SUCCESS = {**ROW, "metric_name": "ho_success", "unit": "count", "n": 21, "total": 20.0}


def plan(**kw):
    return json.dumps({"needed": True, "products": [], "modes": [], "counts": [], "metrics": [], "from_no": None, "to_no": None, **kw})


def test_only_a_plan_that_asks_for_numbers_is_used():
    assert stats.parse_plan(plan(modes=["xn"]))["modes"] == ["xn"]
    assert stats.parse_plan('```json\n' + plan() + '\n```') is not None
    assert stats.parse_plan(json.dumps({"needed": False})) is None
    assert stats.parse_plan("not json") is None and stats.parse_plan("") is None


def test_the_plan_becomes_allow_listed_parameters_and_everything_else_is_dropped():
    p = stats.to_query({"needed": True, "products": ["SCU2050", " "], "modes": ["XN", "drop table"], "counts": [100, "7", 10], "metrics": ["ho_success", "x; DROP"],
                        "from_no": 40, "to_no": 99999})
    assert p["products"] == ["SCU2050"] and p["test_cases"] == ["cellular_handover:xn:100", "cellular_handover:xn:10"]
    assert p["metrics"] == ["ho_success"] and p["from_no"] == 40 and p["to_no"] is None
    assert stats.to_query({"needed": True})["test_cases"] is None          # nothing named: every test case
    assert len(stats.to_query({"needed": True, "modes": ["ng", "xn"]})["test_cases"]) == 6


def test_the_query_refuses_what_is_not_on_its_lists():
    with pytest.raises(q.QueryError):
        q.handover_stats(None, test_cases=["cellular_handover:xn:100; select 1"])
    with pytest.raises(q.QueryError):
        q.handover_stats(None, metrics=["throughput"])
    with pytest.raises(q.QueryError):
        q.handover_stats(None, from_no=0)
    with pytest.raises(q.QueryError):
        q.handover_stats(None, products=["a"] * 6)


def test_the_result_is_text_the_answer_can_quote():
    text = stats.render([ROW, SUCCESS], {"from_no": 40, "to_no": 60})
    assert "只計第 40～60 次" in text and "【SCU2050／Xn Handover 100 times】" in text
    assert "換手後延遲：n 21，平均 33.33 ms，最小 26，最大 49，中位數 31，p95 45" in text
    assert "換手成功 20／21 次" in text


def test_a_failure_or_an_empty_result_adds_nothing():
    ok = lambda messages: plan(modes=["xn"])
    assert stats.ReportStats(ok, lambda **p: [ROW]).passages("Xn 的平均延遲")[0]["publisher"] == "資料庫彙總"
    assert stats.ReportStats(ok, lambda **p: []).passages("Xn") == []
    assert stats.ReportStats(lambda m: json.dumps({"needed": False}), lambda **p: [ROW]).passages("目的是什麼") == []
    assert stats.ReportStats(ok, lambda **p: (_ for _ in ()).throw(q.QueryError("沒有這個設備"))).passages("Xn") == []
    assert stats.ReportStats(ok, lambda **p: [ROW], available=lambda: False).passages("Xn") == []


class Catalog:
    def search(self, query, names, top_k=8, include_history=False):
        return [{"doc": {"title": "報告", "revision_id": "r:1", "publisher": "測試報告（CSIT）", "analysis_eligible": True}, "chunk": {"location_label": "4.1", "content": "第 1 次：延遲 30→28 ms"}}]


def ask(complete, with_stats, st):
    events = []
    result = ZoneAgent(Catalog(), complete, stats=st).answer(task_id="t", zone_label="產品驗證專區", zone_names=["產品驗證專區"], question="第 40 到 60 次的平均延遲？", history=[], owner={},
                                                             file_records={}, emit=events.append, with_stats=with_stats)
    return result, events


def test_the_computed_numbers_come_first_and_are_cited_like_any_passage():
    seen = []

    def complete(messages):
        seen.append(messages)
        return "平均延遲 33.33 ms [S1]。"

    st = stats.ReportStats(lambda m: plan(counts=[100], from_no=40, to_no=60), lambda **p: [ROW])
    result, events = ask(complete, True, st)
    assert "[S1] 測試數據彙總" in seen[0][-1]["content"] and "[S2] 報告" in seen[0][-1]["content"]
    assert result["citations"][0]["source"].startswith("測試數據彙總") and result["grounding"]["summary"]["values_not_found"] == 0
    assert {"tool": "query_test_data"} in result["trace"] and any(e.get("label") == "查詢測試數據" for e in events)


def test_a_zone_without_report_numbers_never_asks():
    calls = []
    st = stats.ReportStats(lambda m: calls.append(m) or plan(), lambda **p: [ROW])
    result, _ = ask(lambda messages: "沒有。", False, st)
    assert calls == [] and {"tool": "query_test_data"} not in result["trace"]
