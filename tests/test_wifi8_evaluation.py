import importlib.util
import json
from pathlib import Path

import pytest

from src.wifi8.evaluation import fact_hits, load_cases, score_answer, score_retrieval, summarize

GOLDEN = Path(__file__).resolve().parent.parent / "eval" / "wifi8" / "golden-set.v1.jsonl"


def test_golden_set_is_well_formed():
    cases = load_cases(GOLDEN)
    assert len(cases) >= 30
    assert {"功能定義", "測試驗證", "版本判斷", "會議紀錄", "廠商產品", "應拒答"} <= {c["category"] for c in cases}
    for case in cases:
        if case["expect_refusal"]:
            assert not case["gold"] and not case["facts"]
        else:
            assert case["facts"] and all(group for group in case["facts"])
            assert len(case["gold"]) == len(case["gold_titles"])


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
