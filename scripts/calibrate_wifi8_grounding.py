"""Calibrate the grounding similarity thresholds from an evaluation run (results.json).

Positives: each answer claim vs the chunks it actually cites (as computed by the agent run).
Negatives: the same claim vs the chunks cited by a different question (unrelated text).
Run inside the zone's search worker:

  docker exec -w /app <worker> python /tmp/km-eval/calibrate_wifi8_grounding.py \
      --results /tmp/km-eval/ground-all/results.json [--candidate-wifi8 DIR]

Prints the two distributions and suggested KM_WIFI8_GROUNDING_SIM_HIGH / _LOW:
LOW  = 90th percentile of negatives (below it a claim looks like unrelated text),
HIGH = 99th percentile of negatives (above it almost no unrelated text reaches).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    if not values:
        return float("nan")
    index = min(len(values) - 1, max(0, round(q * (len(values) - 1))))
    return values[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--candidate-wifi8", default="")
    args = parser.parse_args()
    if args.candidate_wifi8:
        import src.wifi8
        src.wifi8.__path__.insert(0, str(Path(args.candidate_wifi8).resolve()))
    from src.vector_store import VectorStore
    from src.wifi8.grounding import GroundingSettings, _similarities
    from src.wifi8.importer import Wifi8Importer, Wifi8Settings
    from src.wifi8.search import Wifi8Search

    vs = VectorStore()
    search = Wifi8Search.for_current(Wifi8Importer(Wifi8Settings.from_environment()), qdrant=vs.client, encoder=vs.encode,
                                     embedding_model=vs.model_name, reranker=None)
    rows = [r for r in json.loads(Path(args.results).read_text(encoding="utf-8"))["cases"]
            if (r.get("output") or {}).get("grounding", {}).get("claims")]
    texts = {}
    for row in rows:
        ids = [c["point_id"] for c in row["output"]["citations"] if c.get("point_id")]
        texts.update({pid: chunk["content"] for pid, chunk in search.chunks(ids).items()})
    settings = GroundingSettings.from_environment()
    positives, negatives = [], []
    for i, row in enumerate(rows):
        positives += [c["similarity"] for c in row["output"]["grounding"]["claims"] if c.get("similarity") is not None]
        other = rows[(i + 1) % len(rows)]
        sources = {f"N{j}": {"text": texts.get(c["point_id"], "")} for j, c in enumerate(other["output"]["citations"]) if c.get("point_id")}
        claims = [{"text": c["text"], "refs": list(sources)} for c in row["output"]["grounding"]["claims"] if c.get("refs")]
        _similarities(claims, sources, vs.encode, settings)
        negatives += [c["similarity"] for c in claims if c.get("similarity") is not None]
    report = {"answers": len(rows), "positives": len(positives), "negatives": len(negatives)}
    for name, values in (("positive", positives), ("negative", negatives)):
        report[name] = {f"p{int(q * 100)}": round(percentile(values, q), 4) for q in (0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)}
    low, high = percentile(negatives, 0.9), percentile(negatives, 0.99)
    report["suggested"] = {"KM_WIFI8_GROUNDING_SIM_LOW": round(low, 2), "KM_WIFI8_GROUNDING_SIM_HIGH": round(high, 2),
                           "positives_low": round(sum(p < low for p in positives) / max(1, len(positives)), 3),
                           "positives_high": round(sum(p >= high for p in positives) / max(1, len(positives)), 3)}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
