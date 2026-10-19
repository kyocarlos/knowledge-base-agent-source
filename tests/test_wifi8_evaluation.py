import importlib.util
import json
from pathlib import Path

import pytest

from src.wifi8.evaluation import fact_hits, load_cases, score_answer, score_retrieval, summarize, unnumbered_repeats

GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "wifi8" / "golden-set.v1.jsonl"


def test_golden_set_is_well_formed():
    cases = load_cases(GOLDEN)
    assert len(cases) >= 30
    assert {"功能定義", "測試驗證", "版本判斷", "會議紀錄", "廠商產品", "應拒答"} <= {c["category"] for c in cases}
    for case in cases:
        if case["expect_refusal"]:
            assert not case["gold"] and not case["facts"]
        else:
            assert (case["facts"] or case.get("list_gold")) and all(group for group in case["facts"])
            assert len(case["gold"]) == len(case["gold_titles"])
    assert {"議程規範", "混淆防護", "推理與摘要", "安全與模糊", "拒答不補推測", "列舉"} <= {c["category"] for c in cases}
    lists = [c for c in cases if c["category"] == "列舉"]
    assert len(lists) >= 4 and all(c["list_gold"] and c["expect_tool"] == "find_documents" for c in lists)
    refusals = [c for c in cases if c["category"] == "拒答不補推測"]
    assert refusals and all(c["expect_refusal"] and c["must_not_regex"] for c in refusals)  # refusals also forbid invented advice
    figures = [c for c in cases if c["category"] == "圖片圖表"]
    assert len(figures) >= 6 and all(c["gold_figures"] and c["gold"] for c in figures)
    assert all(len(f) == 64 for c in figures for f in c["gold_figures"])


def test_load_cases_rejects_duplicates_and_incomplete_refusals(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("\n".join(json.dumps(c) for c in [{"id": "A", "question": "q", "gold": [], "facts": []}] * 2))
    with pytest.raises(ValueError, match="duplicate"):
        load_cases(path)
    path.write_text(json.dumps({"id": "A", "question": "q", "gold": [], "facts": [], "expect_refusal": True}))
    with pytest.raises(ValueError, match="refusal_markers"):
        load_cases(path)


def test_fact_groups_match_any_spelling_ignoring_case_and_spaces():
    assert fact_hits("ELR 只用於 UL，速率 3.33 Mbps", [["uplink", "UL"], ["3.33"], ["DL only"]]) == [True, True, False]
    assert fact_hits("支援 320MHz 頻寬", [["320 MHz"]]) == [True]


def test_retrieval_rank_counts_documents_not_chunks():
    case = {"gold": ["g1", "g2"]}
    results = [{"revision_id": "x"}, {"revision_id": "x"}, {"revision_id": "g2"}]
    assert score_retrieval(case, results) == {"applicable": True, "hit": True, "rank": 2, "mrr": 0.5}
    assert score_retrieval(case, [{"revision_id": "x"}])["hit"] is False
    assert score_retrieval({"gold": []}, results) == {"applicable": False}


def test_answer_needs_all_facts_and_a_gold_citation():
    case = {"gold": ["g1"], "facts": [["PF2"]]}
    assert score_answer(case, {"answer": "從 PF2 開始", "citations": [{"revision_id": "g1"}]})["passed"]
    assert not score_answer(case, {"answer": "從 PF2 開始", "citations": [{"revision_id": "other"}]})["passed"]
    assert not score_answer(case, {"answer": "從 PF3 開始", "citations": [{"revision_id": "g1"}]})["passed"]
    assert score_answer({"gold": [], "facts": [["368"]]}, {"answer": "共 368 份", "citations": []})["passed"]


def test_refusal_cases_fail_on_invented_numbers():
    case = {"gold": [], "facts": [], "expect_refusal": True, "refusal_markers": ["找不到"], "must_not_regex": [r"\$ ?\d"]}
    assert score_answer(case, {"answer": "資料中找不到認證費用。"})["passed"]
    assert not score_answer(case, {"answer": "認證費用約 $5000。"})["passed"]
    assert not score_answer(case, {"answer": "找不到官方價格，但估計約 $5000。"})["passed"]


def test_summary_and_report():
    rows = [
        {"id": "A", "category": "c1", "retrieval": {"applicable": True, "hit": True, "rank": 1, "mrr": 1.0},
         "answer": {"passed": True, "fact_coverage": 1.0, "cited_gold": True, "fact_hits": [True]}, "elapsed_ms": 1000},
        {"id": "B", "category": "c1", "question": "q", "retrieval": {"applicable": True, "hit": False, "rank": None, "mrr": 0.0},
         "answer": {"passed": False, "fact_coverage": 0.5, "cited_gold": False, "fact_hits": [True, False]}, "elapsed_ms": 3000},
    ]
    summary = summarize(rows)
    assert summary["overall"]["retrieval_hit_at_k"] == 0.5 and summary["overall"]["answer_pass"] == 0.5
    assert summary["overall"]["fact_coverage"] == 0.75 and summary["by_category"]["c1"]["cases"] == 2

    spec = importlib.util.spec_from_file_location("eval_wifi8_agent", Path(__file__).resolve().parent.parent / "scripts" / "eval_wifi8_agent.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    report = runner.render_report({"created_utc": "t", "source_commit": "abc", "package_id": "p", "cases_file": "g.jsonl",
                                   "agent": None, "summary": summary, "cases": rows})
    assert "| 整體 | 2 | 50.0% |" in report
    assert "**B** q：檢索前 10 筆沒有標準來源；缺少事實組 [2]；引用未包含標準來源" in report


def test_rescore_reuses_saved_answers_without_llm(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("eval_wifi8_agent", Path(__file__).resolve().parent.parent / "scripts" / "eval_wifi8_agent.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)

    class FakeSearch:
        package_id = "p1"

        def search(self, question, options):
            return {"results": [{"revision_id": "g1"}]}

    built = []
    monkeypatch.setattr(runner, "build", lambda retrieval_only: built.append(retrieval_only) or (FakeSearch(), None, None))
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in [
        {"id": "A", "category": "c", "question": "q1", "gold": ["g1"], "facts": [["PF2"]]},
        {"id": "B", "category": "c", "question": "q2", "gold": ["g1"], "facts": [["368"]], "package_id": "other"},
    ]), encoding="utf-8")
    previous = tmp_path / "prev.json"
    previous.write_text(json.dumps({"created_utc": "t0", "agent": {"model": "m"}, "cases": [
        {"id": "A", "elapsed_ms": 5, "output": {"answer": "從 PF2 開始", "citations": [{"revision_id": "g1"}]}}]}), encoding="utf-8")
    out = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["x", "--cases", str(cases), "--out", str(out), "--rescore", str(previous)])
    assert runner.main() == 0
    result = json.loads((out / "results.json").read_text(encoding="utf-8"))
    assert built == [True]  # no LLM client is built when re-scoring
    assert result["agent"] == {"model": "m", "rescored_from": "t0"}
    rows = {r["id"]: r for r in result["cases"]}
    assert rows["A"]["answer"]["passed"] and rows["A"]["retrieval"]["hit"] and rows["A"]["elapsed_ms"] == 5
    assert rows["B"]["skipped"].startswith("case is bound to package")


def test_fact_matching_ignores_unicode_dash_variants():
    assert fact_hits("最高調變為 4K\u2011QAM，Wi\u2011Fi 8", [["4K-QAM"], ["Wi-Fi 8"]]) == [True, True]
    assert fact_hits("Co\u2013BF", [["Co-BF"]]) == [True]


def test_fact_matching_treats_multiplication_sign_as_x():
    assert fact_hits("BCM43840 是 4×4，BCM43820 是 2×2", [["4x4"], ["2x2"]]) == [True, True]


def test_fact_matching_ignores_markdown_emphasis():
    assert fact_hits("參加設備：6 台 **AP**、7 台 **STA**", [["6 台 AP"], ["7 台 STA"]]) == [True, True]


def test_figure_cases_need_a_gold_figure_in_search_and_citations():
    case = {"gold": ["g1"], "facts": [["HVAC"]], "gold_figures": ["img1"]}
    results = [{"revision_id": "g1"}, {"revision_id": "x", "image": {"id": "other"}}, {"revision_id": "g1", "image": {"id": "img1"}}]
    assert score_retrieval(case, results) == {"applicable": True, "hit": True, "rank": 1, "mrr": 1.0, "figure_hit": True, "figure_rank": 3}
    assert score_retrieval(case, results[:2])["figure_hit"] is False
    assert "figure_hit" not in score_retrieval({"gold": ["g1"]}, results)
    text_only = score_answer(case, {"answer": "依 Occupancy 控制 HVAC", "citations": [{"revision_id": "g1"}]})
    assert text_only["passed"] and text_only["cited_figure"] is False  # a figure miss is reported, not a failed answer
    assert score_answer(case, {"answer": "HVAC", "citations": [{"revision_id": "g1", "image": {"id": "img1"}}]})["cited_figure"]
    assert "cited_figure" not in score_answer({"gold": ["g1"], "facts": [["x"]]}, {"answer": "x", "citations": []})


def test_repeated_places_must_be_numbered():
    page3 = {"revision_id": "d", "location_label": "第 3 頁"}
    assert unnumbered_repeats([page3, {**page3, "location_label": "第 6 頁"}]) == 0  # different places
    assert unnumbered_repeats([page3, page3]) == 2
    assert unnumbered_repeats([{**page3, "part": {"index": 1, "total": 2}}, {**page3, "part": {"index": 2, "total": 2}}]) == 0
    assert unnumbered_repeats([page3, {**page3, "revision_id": "other"}]) == 0  # same label, other document
    scored = score_answer({"gold": ["d"], "facts": [["x"]]}, {"answer": "x", "citations": [page3, page3]})
    assert scored["unnumbered_repeats"] == 2


def test_summary_and_report_for_figure_checks():
    rows = [
        {"id": "F1", "category": "圖片圖表", "question": "q", "retrieval": {"applicable": True, "hit": True, "rank": 1, "mrr": 1.0, "figure_hit": False},
         "answer": {"passed": True, "fact_coverage": 1.0, "cited_gold": True, "fact_hits": [True], "cited_figure": False, "unnumbered_repeats": 0}},
        {"id": "F2", "category": "圖片圖表", "retrieval": {"applicable": True, "hit": True, "rank": 1, "mrr": 1.0, "figure_hit": True},
         "answer": {"passed": True, "fact_coverage": 1.0, "cited_gold": True, "fact_hits": [True], "cited_figure": True, "unnumbered_repeats": 0}},
        {"id": "A", "category": "c", "question": "q2", "retrieval": {"applicable": True, "hit": True, "rank": 1, "mrr": 1.0},
         "answer": {"passed": True, "fact_coverage": 1.0, "cited_gold": True, "fact_hits": [True], "unnumbered_repeats": 2}},
    ]
    overall = summarize(rows)["overall"]
    assert (overall["figure_cases"], overall["retrieval_figure_hit_at_k"], overall["cited_figure"], overall["unnumbered_repeat_answers"]) == (2, 0.5, 0.5, 1)
    assert summarize([{"id": "R", "category": "c", "retrieval": {"applicable": True, "hit": True, "rank": 1, "mrr": 1.0}}])["overall"]["unnumbered_repeat_answers"] is None

    spec = importlib.util.spec_from_file_location("eval_wifi8_agent", Path(__file__).resolve().parent.parent / "scripts" / "eval_wifi8_agent.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    report = runner.render_report({"created_utc": "t", "source_commit": "abc", "package_id": "p", "cases_file": "g.jsonl",
                                   "agent": None, "summary": summarize(rows), "cases": rows})
    assert "圖片題 2 題：檢索前 10 筆有標準圖片 50.0%；回答引用標準圖片 50.0%" in report
    assert "**F1** q：檢索前 10 筆沒有標準圖片；引用未包含標準圖片" in report
    assert "**A** q2：同一位置的引用有 2 筆沒有標出第幾段" in report and "**F2**" not in report


def test_figure_cases_resolve_titles_places_and_shared_figures(tmp_path):
    spec = importlib.util.spec_from_file_location("figure_cases", Path(__file__).resolve().parent.parent / "eval" / "wifi8" / "figure_cases.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docs = [{"revision_id": "a", "title": "Deck A v1", "analysis_eligible": True}, {"revision_id": "b", "title": "Article B", "analysis_eligible": True},
            {"revision_id": "old", "title": "Deck A v0", "analysis_eligible": False}]
    images = [{"revision_id": "a", "image_id": "1" * 64, "ordinal": 2, "location": {"type": "slide", "slide": 5}},
              {"revision_id": "a", "image_id": "2" * 64, "ordinal": 3, "location": {"type": "slide", "slide": 5}},
              {"revision_id": "b", "image_id": "1" * 64, "ordinal": 1, "location": {"type": "image"}},
              {"revision_id": "old", "image_id": "1" * 64, "ordinal": 2, "location": {"type": "slide", "slide": 5}}]
    for name, rows in (("documents.jsonl", docs), ("images.jsonl", images)):
        (tmp_path / name).write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    module.CASES = [dict(id="F1", question="q", facts=[["x"]], figures=[("Deck A", 2, {"slide": 5}), ("Article B", 1, {})])]
    case = module.figure_cases(tmp_path)[0]
    assert case["gold"] == ["a", "b"] and case["gold_figures"] == ["1" * 64]  # the figure shared by both documents counts once
    assert case["gold_figure_places"] == ["Deck A v1｜投影片 5・圖 2", "Article B｜圖 1"] and case["category"] == "圖片圖表"
    module.CASES = [dict(id="F2", question="q", facts=[["x"]], figures=[("Deck A", 9, {})])]
    with pytest.raises(AssertionError):
        module.figure_cases(tmp_path)  # a figure that cannot be found is an error, not a silently smaller case

    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"id": "D1", "category": "功能定義"}) + "\n" + json.dumps({"id": "F0", "category": "圖片圖表"}) + "\n", encoding="utf-8")
    module.CASES = [dict(id="F1", question="q", facts=[["x"]], figures=[("Article B", 1, {})])]
    import sys
    argv, sys.argv = sys.argv, ["figure_cases.py", str(tmp_path), str(golden)]
    try:
        module.main()
    finally:
        sys.argv = argv
    assert [json.loads(l)["id"] for l in golden.read_text(encoding="utf-8").splitlines()] == ["D1", "F1"]


def test_list_cases_score_the_share_of_expected_titles_named_in_the_answer():
    case = {"id": "L", "question": "q", "gold": [], "facts": [], "expect_refusal": False, "expect_tool": "find_documents",
            "list_gold": ["Flow Matching for Multi-AP", "A Tutorial on Wi-Fi 8", "Deep Reinforcement"], "min_recall": 0.5}
    full = score_answer(case, {"answer": "1. Flow Matching for Multi‑AP Coordination 2. A Tutorial on Wi‑Fi 8 3. Deep Reinforcement Learning",
                               "citations": [], "tools": ["find_documents"]})
    assert full["list_recall"] == 1.0 and full["list_missing"] == [] and full["passed"] and full["used_expected_tool"] is True
    half = score_answer(case, {"answer": "只有 Flow Matching for Multi-AP。", "citations": [], "trace": [{"tool": "search_wifi"}]})
    assert half["list_recall"] == 0.3333 and not half["passed"] and half["used_expected_tool"] is False  # below min_recall, tool not used
    assert score_answer({**case, "min_recall": 0.3}, {"answer": "Flow Matching for Multi-AP", "citations": []})["passed"]


def test_forbidden_content_fails_any_case_and_refusals_keep_reporting_it_as_invented():
    advice = [r"通常", r"建議.{0,6}詢價"]
    answerable = {"id": "A", "question": "q", "gold": [], "facts": [["25"]], "expect_refusal": False, "must_not_regex": advice}
    assert score_answer(answerable, {"answer": "數值是 25。", "citations": []})["passed"]
    bad = score_answer(answerable, {"answer": "數值是 25，通常如此。", "citations": []})
    assert not bad["passed"] and bad["forbidden"] == ["通常"]
    refusal = {"id": "R", "question": "q", "gold": [], "facts": [], "expect_refusal": True, "refusal_markers": ["沒有"], "must_not_regex": advice}
    assert score_answer(refusal, {"answer": "文件沒有提供費用。", "citations": []})["passed"]
    spec = score_answer(refusal, {"answer": "文件沒有提供費用，建議向實驗室詢價。", "citations": []})
    assert not spec["passed"] and spec["invented"] == ["建議.{0,6}詢價"]
    rows = [{"category": "x", "answer": spec}, {"category": "x", "answer": bad}, {"category": "x", "answer": {"passed": True, "forbidden": []}}]
    assert summarize(rows)["overall"]["forbidden_answers"] == 2


def test_summary_reports_list_recall_and_expected_tool_rate():
    rows = [{"category": "列舉", "answer": {"passed": True, "list_recall": 1.0, "used_expected_tool": True}},
            {"category": "列舉", "answer": {"passed": False, "list_recall": 0.5, "used_expected_tool": False}}]
    overall = summarize(rows)["overall"]
    assert overall["list_cases"] == 2 and overall["list_recall"] == 0.75 and overall["expected_tool_rate"] == 0.5


def test_behavior_cases_resolve_gold_and_compute_lists_from_the_package(tmp_path):
    spec = importlib.util.spec_from_file_location("behavior_cases", GOLDEN.parent / "behavior_cases.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    docs = [{"revision_id": "a", "title": "arXiv - Paper A about reuse - arXiv 2501.00001", "analysis_eligible": True, "publisher": "arXiv"},
            {"revision_id": "b", "title": "arXiv - Paper B passing mention - arXiv 2501.00002", "analysis_eligible": True, "publisher": "arXiv"},
            {"revision_id": "c", "title": "arXiv - Old paper - arXiv 2401.00003", "analysis_eligible": False, "publisher": "arXiv"},
            {"revision_id": "d", "title": "WFA - Agenda 1", "analysis_eligible": True, "publisher": "WFA"}]
    segments = [{"revision_id": "a", "text": "reuse reuse reuse"}, {"revision_id": "b", "text": "reuse"}, {"revision_id": "c", "text": "reuse reuse reuse reuse"}]
    for name, rows in (("documents.jsonl", docs), ("segments.jsonl", segments)):
        (tmp_path / name).write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    module.CASES = [dict(id="B1", category="議程規範", question="q", gold_titles=["WFA - Agenda"], facts=[["x"]])]
    module.LISTS = [dict(id="L1", question="q", pattern=r"reuse", flags="i", min_mentions=3, publisher="arXiv")]
    cases = module.behavior_cases(tmp_path)
    assert cases[0]["gold"] == ["d"] and cases[0]["gold_titles"] == ["WFA - Agenda 1"]
    assert cases[1]["list_gold"] == ["Paper A about reuse"] and cases[1]["expect_tool"] == "find_documents"  # b: too few mentions, c: not current
    module.CASES = [dict(id="B3", category="議程規範", question="q", gold_titles=["Old"], facts=[["x"]], history=True)]
    module.LISTS = []
    docs.append({"revision_id": "e", "title": "Old paper v1", "analysis_eligible": False, "publisher": "WFA"})
    (tmp_path / "documents.jsonl").write_text("\n".join(json.dumps(r) for r in docs), encoding="utf-8")
    assert module.behavior_cases(tmp_path)[0]["gold"] == ["e"]  # a version question accepts superseded versions as sources
    module.CASES = [dict(id="B2", category="議程規範", question="q", gold_titles=["No such title"], facts=[["x"]])]
    with pytest.raises(AssertionError):
        module.behavior_cases(tmp_path)  # a gold document that cannot be found is an error
