"""Golden-set evaluation for the WiFi zone search and agent.

Scoring is plain code (no model judges): a case lists gold documents (any one counts),
fact groups (each group is a list of accepted spellings; a group matches when any
spelling appears in the answer), and for unanswerable questions the refusal markers
and patterns that must not appear (e.g. invented prices).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

RETRIEVAL_K = 10


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case id")
    for case in cases:
        if not case.get("question") or not isinstance(case.get("gold"), list) or not isinstance(case.get("facts"), list):
            raise ValueError(f"case {case.get('id')} is missing question/gold/facts")
        if case.get("expect_refusal") and not case.get("refusal_markers"):
            raise ValueError(f"case {case['id']} expects a refusal but has no refusal_markers")
    return cases


_DASHES = str.maketrans({**{c: "-" for c in "\u2010\u2011\u2012\u2013\u2014\u2212\ufe63\uff0d"},
                          "\u00d7": "x", "\uff58": "x"})  # 4×4 → 4x4


def _norm(text: str) -> str:
    """Case-, whitespace-, dash- and multiplication-sign-insensitive form (models often write Wi‑Fi, 4×4)."""
    text = re.sub(r"\*\*|__|`", "", str(text or ""))  # markdown emphasis: "6 台 **AP**" ~ "6 台 AP"
    return re.sub(r"\s+", "", text.translate(_DASHES)).casefold()


def fact_hits(answer: str, facts: Iterable[Iterable[str]]) -> list[bool]:
    norm = _norm(answer)
    return [any(_norm(option) in norm for option in group) for group in facts]


def score_retrieval(case: dict[str, Any], results: list[dict[str, Any]], k: int = RETRIEVAL_K) -> dict[str, Any]:
    gold = set(case["gold"])
    if not gold:
        return {"applicable": False}
    ranked = list(dict.fromkeys(r["revision_id"] for r in results))[:k]
    rank = next((i for i, rid in enumerate(ranked, 1) if rid in gold), None)
    return {"applicable": True, "hit": rank is not None, "rank": rank, "mrr": 1.0 / rank if rank else 0.0}


def score_answer(case: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    answer = output.get("answer") or ""
    cited = {c.get("revision_id") for c in output.get("citations") or []}
    if case.get("expect_refusal"):
        refused = any(_norm(m) in _norm(answer) for m in case["refusal_markers"])
        invented = [p for p in case.get("must_not_regex") or [] if re.search(p, answer)]
        return {"refused": refused, "invented": invented, "fact_coverage": None, "cited_gold": None,
                "passed": refused and not invented}
    hits = fact_hits(answer, case["facts"])
    coverage = sum(hits) / len(hits) if hits else 1.0
    cited_gold = bool(cited & set(case["gold"])) if case["gold"] else None
    return {"fact_hits": hits, "fact_coverage": coverage, "cited_gold": cited_gold,
            "passed": coverage == 1.0 and cited_gold is not False}


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def block(items: list[dict[str, Any]]) -> dict[str, Any]:
        retrieval = [r["retrieval"] for r in items if r.get("retrieval", {}).get("applicable")]
        answers = [r["answer"] for r in items if r.get("answer")]
        coverage = [a["fact_coverage"] for a in answers if a.get("fact_coverage") is not None]
        cited = [a["cited_gold"] for a in answers if a.get("cited_gold") is not None]
        latency = sorted(r["elapsed_ms"] for r in items if r.get("elapsed_ms") is not None)
        retrieval_ms = sorted(r["retrieval_ms"] for r in items if r.get("retrieval_ms") is not None)
        return {
            "cases": len(items),
            "retrieval_hit_at_k": _ratio(sum(r["hit"] for r in retrieval), len(retrieval)),
            "retrieval_mrr": _mean([r["mrr"] for r in retrieval]),
            "answer_pass": _ratio(sum(a["passed"] for a in answers), len(answers)),
            "fact_coverage": _mean(coverage),
            "cited_gold": _ratio(sum(cited), len(cited)),
            "latency_ms_p50": latency[len(latency) // 2] if latency else None,
            "latency_ms_max": latency[-1] if latency else None,
            "retrieval_ms_p50": retrieval_ms[len(retrieval_ms) // 2] if retrieval_ms else None,
            "retrieval_ms_max": retrieval_ms[-1] if retrieval_ms else None,
            "errors": sum(1 for r in items if r.get("error")),
        }
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    return {"overall": block(rows), "by_category": {name: block(items) for name, items in by_category.items()}}


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None
