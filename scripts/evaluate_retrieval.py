"""Offline retrieval metrics for versioned KM qrels and result snapshots."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def load_json(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_qrels(qrels: list[dict[str, Any]], require_labels: bool = False) -> None:
    if not qrels:
        raise ValueError("qrels must not be empty")
    seen = set()
    for item in qrels:
        query_id = str(item.get("query_id") or "").strip()
        if not query_id or query_id in seen:
            raise ValueError("query_id must be present and unique")
        if not str(item.get("query") or "").strip():
            raise ValueError(f"{query_id}: query is required")
        seen.add(query_id)
        chunks = item.get("relevant_chunks") or []
        for chunk in chunks:
            relevance = chunk.get("relevance")
            if not str(chunk.get("chunk_id") or "").strip() or relevance not in {0, 1, 2, 3}:
                raise ValueError(f"{query_id}: invalid relevant_chunks entry")
        if require_labels and not chunks:
            raise ValueError(f"{query_id}: manual chunk labels are required")


def _relevance_map(qrel: dict[str, Any]) -> dict[str, int]:
    return {str(item["chunk_id"]): int(item["relevance"]) for item in qrel.get("relevant_chunks", [])}


def _ids(results: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("chunk_id") or item.get("id") or "") for item in results]


def score_query(qrel: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, float]:
    relevant = _relevance_map(qrel)
    ranked = _ids(results)

    def at(k: int) -> list[str]:
        return ranked[:k]

    top5 = at(5)
    top10 = at(10)
    top20 = at(20)
    positive = {key for key, value in relevant.items() if value > 0}
    precision5 = sum(item in positive for item in top5) / max(len(top5), 1)
    recall20 = sum(item in positive for item in top20) / max(len(positive), 1)
    hit5 = float(any(item in positive for item in top5))
    reciprocal = next((1.0 / (index + 1) for index, item in enumerate(top10) if item in positive), 0.0)

    def dcg(items: list[str]) -> float:
        return sum((2 ** relevant.get(item, 0) - 1) / math.log2(index + 2) for index, item in enumerate(items))

    ideal = sorted(relevant.values(), reverse=True)[:10]
    ideal_dcg = sum((2 ** value - 1) / math.log2(index + 2) for index, value in enumerate(ideal))
    ndcg10 = dcg(top10) / ideal_dcg if ideal_dcg else 0.0
    return {
        "precision_at_5": precision5,
        "recall_at_20": recall20,
        "hit_rate_at_5": hit5,
        "mrr_at_10": reciprocal,
        "ndcg_at_10": ndcg10,
    }


def evaluate(qrels: list[dict[str, Any]], results: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    rows = []
    for qrel in qrels:
        metrics = score_query(qrel, results.get(str(qrel["query_id"]), []))
        rows.append({"query_id": qrel["query_id"], **metrics})
    keys = list(rows[0].keys())[1:] if rows else []
    return {
        "queries": len(rows),
        "metrics": {key: round(sum(row[key] for row in rows) / len(rows), 6) for key in keys} if rows else {},
        "per_query": rows,
    }


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    """Return release-gate violations; values are proportions, not percentages."""
    base = baseline.get("metrics", {})
    new = candidate.get("metrics", {})
    violations = []
    if new.get("recall_at_20", 0.0) < base.get("recall_at_20", 0.0):
        violations.append("recall_at_20_regressed")
    for key in ("precision_at_5", "mrr_at_10", "ndcg_at_10"):
        if new.get(key, 0.0) < base.get(key, 0.0) - 0.02:
            violations.append(f"{key}_regressed_over_2_points")
    primary = ("precision_at_5", "mrr_at_10", "ndcg_at_10", "recall_at_20")
    if not any(new.get(key, 0.0) >= base.get(key, 0.0) * 1.05 for key in primary if base.get(key, 0.0) > 0):
        violations.append("no_primary_metric_improved_by_5_percent")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qrels", required=True)
    parser.add_argument("--results")
    parser.add_argument("--output")
    parser.add_argument("--require-labels", action="store_true")
    parser.add_argument("--baseline-report")
    parser.add_argument("--candidate-report")
    args = parser.parse_args()
    qrels = load_json(args.qrels)
    if not isinstance(qrels, list):
        raise ValueError("qrels must be a JSON list")
    validate_qrels(qrels, require_labels=args.require_labels)
    report = {"qrels": args.qrels, "queries": len(qrels), "status": "validated"}
    if args.results:
        results = load_json(args.results)
        report = {"qrels": args.qrels, "status": "evaluated", **evaluate(qrels, results)}
    if args.baseline_report or args.candidate_report:
        if not args.baseline_report or not args.candidate_report:
            raise ValueError("baseline-report and candidate-report must be supplied together")
        violations = compare_reports(load_json(args.baseline_report), load_json(args.candidate_report))
        report = {"status": "comparison", "violations": violations, "gate": "PASS" if not violations else "FAIL"}
        if violations:
            rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
            if args.output:
                Path(args.output).write_text(rendered, encoding="utf-8")
            else:
                print(rendered, end="")
            return 1
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
