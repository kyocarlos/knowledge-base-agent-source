"""Run the WiFi zone golden set against the live search and agent of one KM data zone.

Run inside that zone's search worker (it has Qdrant, the embedding model and the
primary LLM settings), with the repository's `src` importable, e.g.:

  docker exec -w /app kb-celery-search python /tmp/eval_wifi8_agent.py \
      --cases /tmp/golden-set.v1.jsonl --out /tmp/wifi8-eval [--retrieval-only] [--ids D01,T02]

Writes results.json (per case + summary) and report.md. Answers are not cached;
every agent run calls the primary LLM once per step.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

# Scoring rules follow the runner and the case file, not the deployed image: a copy of
# evaluation.py placed next to this script wins over the one inside the image.
if (Path(__file__).resolve().parent / "evaluation.py").is_file():
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from evaluation import load_cases, score_answer, score_retrieval, summarize, supports  # type: ignore[no-redef]
else:
    from src.wifi8.evaluation import load_cases, score_answer, score_retrieval, summarize, supports


def build(retrieval_only: bool):
    from src.main import load_config
    from src.vector_store import VectorStore
    from src.web_api.ollama_client import _build_primary_client
    from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools, run_agent
    from src.wifi8.importer import Wifi8Importer, Wifi8Settings
    from src.wifi8.search import Wifi8Search

    vector_store = VectorStore()
    search = Wifi8Search.for_current(Wifi8Importer(Wifi8Settings.from_environment()), qdrant=vector_store.client,
                                     encoder=vector_store.encode, embedding_model=vector_store.model_name)
    if retrieval_only:
        return search, None, None
    client, label = _build_primary_client(load_config())
    if client is None:
        raise SystemExit("primary LLM is not configured; use --retrieval-only")
    settings = AgentSettings.from_environment()

    def agent(question: str, history: list[dict] | None = None) -> dict:
        return run_agent(question, llm=lambda **kw: client.chat.completions.create(**kw),
                         tools=WifiTools(search, settings, CitationRegistry()), settings=settings, history=history)
    return search, agent, {"model": label, "max_steps": settings.max_steps, "time_budget_seconds": settings.time_budget_seconds}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ids", default="", help="comma separated case ids")
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--candidate-wifi8", default="", help="directory with a candidate src/wifi8 package to evaluate before deploying")
    parser.add_argument("--rerank-model", default=None, help="override KM_WIFI8_RERANK_MODEL for this run ('' disables)")
    parser.add_argument("--rerank-candidates", type=int, default=None, help="override KM_WIFI8_RERANK_CANDIDATES")
    parser.add_argument("--rescore", default="", help="previous results.json: re-score its saved answers (no LLM calls); retrieval is re-run")
    args = parser.parse_args()

    import os
    if args.rerank_model is not None:
        os.environ["KM_WIFI8_RERANK_MODEL"] = args.rerank_model
    if args.rerank_candidates is not None:
        os.environ["KM_WIFI8_RERANK_CANDIDATES"] = str(args.rerank_candidates)
    if args.candidate_wifi8:
        import src.wifi8
        src.wifi8.__path__.insert(0, str(Path(args.candidate_wifi8).resolve()))  # candidate modules shadow the deployed ones
    from src.wifi8.search import SearchOptions
    cases = load_cases(args.cases)
    if args.ids:
        wanted = set(args.ids.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    previous = {}
    if args.rescore:
        saved = json.loads(Path(args.rescore).read_text(encoding="utf-8"))
        previous = {row["id"]: row for row in saved["cases"] if row.get("output")}
    search, agent, agent_info = build(args.retrieval_only or bool(args.rescore))
    if args.rescore:
        agent_info = {**(saved.get("agent") or {}), "rescored_from": saved.get("created_utc")}
    rows = []
    for case in cases:
        row = {"id": case["id"], "category": case["category"], "question": case["question"]}
        if case.get("package_id") and case["package_id"] != search.package_id:
            row["skipped"] = f"case is bound to package {case['package_id']}"
            rows.append(row)
            continue
        try:
            started = time.monotonic()
            found = search.search(case["question"], SearchOptions(top_k=10))["results"]
            row["retrieval_ms"] = round((time.monotonic() - started) * 1000)
            row["retrieval"] = score_retrieval(case, found)
            if case["id"] in previous:
                old = previous[case["id"]]
                row["elapsed_ms"], row["output"] = old.get("elapsed_ms"), old["output"]
                row["answer"] = score_answer(case, {"answer": old["output"]["answer"], "citations": old["output"]["citations"],
                                                    "tools": old["output"].get("tools")})
            elif agent:
                started = time.monotonic()
                output = agent(case["question"], case.get("history"))
                row["elapsed_ms"] = round((time.monotonic() - started) * 1000)
                row["answer"] = score_answer(case, output)
                row["output"] = {"answer": output.get("answer"), "stop_reason": output.get("stop_reason"),
                                 "steps": len(output.get("trace") or []),
                                 "tools": [t.get("tool") for t in output.get("trace") or []],
                                 "citations": [{"ref": c.get("ref"), "revision_id": c.get("revision_id"), "source": c.get("source"),
                                                "point_id": c.get("point_id"), "location_label": c.get("location_label"),
                                                "part": c.get("part"), "image": ({"id": c["image"].get("id")} if c.get("image") else None),
                                                **({"supports_case": supports(case, c)} if case.get("support_regex") else {})}
                                               for c in output.get("citations") or []],
                                 "grounding": output.get("grounding")}
        except Exception as exc:  # one failing case must not hide the rest
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("id", "retrieval", "elapsed_ms", "error", "skipped")}
                         | {"passed": (row.get("answer") or {}).get("passed")}, ensure_ascii=False), flush=True)

    scored = [r for r in rows if not r.get("skipped")]
    result = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source_commit": args.source_commit,
              "package_id": search.package_id, "cases_file": Path(args.cases).name, "agent": agent_info,
              "candidate_wifi8": bool(args.candidate_wifi8),
              "rerank": (search.reranker.settings.__dict__ if getattr(search, "reranker", None) else None),
              "summary": summarize(scored), "cases": rows}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "report.md").write_text(render_report(result), encoding="utf-8")
    print(json.dumps(result["summary"]["overall"], ensure_ascii=False))
    return 0


def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def render_report(result: dict) -> str:
    lines = [f"# WiFi 專區評測報告", "",
             f"- 時間：{result['created_utc']}；匯入版本：`{result['package_id']}`；題庫：`{result['cases_file']}`",
             f"- Rerank：{json.dumps(result.get('rerank'), ensure_ascii=False) if result.get('rerank') else '無'}",
             f"- 程式版本：`{result['source_commit'] or '未提供'}`；Agent：{json.dumps(result['agent'], ensure_ascii=False) if result['agent'] else '只評檢索'}",
             "", "| 類別 | 題數 | 檢索命中@10 | MRR | 回答通過 | 事實覆蓋 | 引用標準來源 | 延遲 p50 (ms) | 錯誤 | 檢索 p50 (ms) |", "|---|---|---|---|---|---|---|---|---|---|"]
    blocks = {**result["summary"]["by_category"], "整體": result["summary"]["overall"]}
    for name, b in blocks.items():
        lines.append(f"| {name} | {b['cases']} | {_pct(b['retrieval_hit_at_k'])} | {b['retrieval_mrr'] if b['retrieval_mrr'] is not None else '—'} | "
                     f"{_pct(b['answer_pass'])} | {_pct(b['fact_coverage'])} | {_pct(b['cited_gold'])} | {b['latency_ms_p50'] or '—'} | {b['errors']} | {b.get('retrieval_ms_p50') or '—'} |")
    overall = result["summary"]["overall"]
    if overall.get("figure_cases") or overall.get("unnumbered_repeat_answers") is not None:
        lines += ["", f"- 圖片題 {overall.get('figure_cases') or 0} 題：檢索前 10 筆有標準圖片 {_pct(overall.get('retrieval_figure_hit_at_k'))}；"
                      f"回答引用標準圖片 {_pct(overall.get('cited_figure'))}",
                  f"- 同一位置多筆引用卻沒有標出第幾段的回答：{'—' if overall.get('unnumbered_repeat_answers') is None else overall['unnumbered_repeat_answers']} 則"]
    if overall.get("list_cases"):
        lines += ["", f"- 列舉題 {overall['list_cases']} 題：平均清單召回 {_pct(overall.get('list_recall'))}；使用預期工具 {_pct(overall.get('expected_tool_rate'))}"]
    if overall.get("forbidden_answers") is not None:
        lines += [f"- 回答含禁止內容（沒有依據的推測、建議或具體數值）：{overall['forbidden_answers']} 則"]
    lines += ["", "## 未通過的題目", ""]
    for row in result["cases"]:
        answer, retrieval = row.get("answer") or {}, row.get("retrieval") or {}
        if row.get("skipped") or (answer.get("passed", True) and retrieval.get("hit", True) and retrieval.get("figure_hit", True)
                                  and answer.get("cited_figure", True) and not answer.get("unnumbered_repeats") and not row.get("error")
                                  and answer.get("used_expected_tool", True)):
            continue
        reasons = []
        if row.get("error"):
            reasons.append(f"錯誤：{row['error']}")
        if retrieval.get("applicable") and not retrieval.get("hit"):
            reasons.append("檢索前 10 筆沒有標準來源")
        if retrieval.get("figure_hit") is False:
            reasons.append("檢索前 10 筆沒有標準圖片")
        if answer.get("fact_hits") and not all(answer["fact_hits"]):
            reasons.append(f"缺少事實組 {[i + 1 for i, hit in enumerate(answer['fact_hits']) if not hit]}")
        if answer.get("cited_gold") is False:
            reasons.append("引用未包含標準來源")
        if answer.get("cited_figure") is False:
            reasons.append("引用未包含標準圖片")
        if answer.get("unnumbered_repeats"):
            reasons.append(f"同一位置的引用有 {answer['unnumbered_repeats']} 筆沒有標出第幾段")
        if answer.get("refused") is False:
            reasons.append("應拒答但未拒答")
        if answer.get("invented"):
            reasons.append("出現不應有的內容（具體數值或沒有依據的建議）")
        if answer.get("forbidden"):
            reasons.append("回答含此題禁止的內容")
        if answer.get("list_missing"):
            reasons.append(f"清單召回 {_pct(answer.get('list_recall'))}，沒列出：{'、'.join(answer['list_missing'])}")
        if answer.get("used_expected_tool") is False:
            reasons.append("沒有使用預期的工具")
        lines.append(f"- **{row['id']}** {row['question']}：{'；'.join(reasons)}")
    skipped = [r for r in result["cases"] if r.get("skipped")]
    if skipped:
        lines += ["", "## 略過", ""] + [f"- {r['id']}：{r['skipped']}" for r in skipped]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
