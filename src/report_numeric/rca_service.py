"""One place that turns 'these report ids and a question' into a comparison pack plus a verified cause analysis.
Used by the Celery task (so the web process never waits for the model) and by tests; it has no web or Celery dependency."""
from __future__ import annotations

from typing import Callable

from . import compare, rca


def analyze(connect: Callable, roles: list[str], llm: Callable[[list[dict]], str], run_ids: list[str], question: str = "") -> dict:
    """Raises compare.CompareError for a bad selection. A model failure never loses the comparison: it is reported as status 'unavailable'."""
    with connect() as conn:
        pack = compare.compare_runs(compare.load_runs(conn, run_ids, roles), compare.load_directions(conn))
    try:
        out = rca.run_rca(pack, llm, question=(question or "").strip())
    except Exception as exc:  # noqa: BLE001 - network, timeout, malformed client reply
        name = type(exc).__name__
        reason = "模型回應逾時" if "Timeout" in name else "模型暫時無法使用（" + name + "）"
        out = {"status": "unavailable", "analysis": None, "violations": [reason], "warnings": [], "attempts": 0}
    return {"pack": pack, "rca": out}
