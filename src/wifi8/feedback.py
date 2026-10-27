"""Thumbs up/down on an agent answer, kept as one small JSON file per task under the zone's data root.

The record carries what is needed to look at the case later (question, the start of the answer, cited titles, tools, grounding summary, flags) but is only
written for a task that exists and belongs to the rater. Re-rating the same task replaces the earlier rating. The summary endpoint exposes counts only.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

TASK_ID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
COMMENT_CHARS = 500
# key -> label. The page asks for this list instead of carrying its own copy.
REASONS = {
    "wrong_fact": "內容有誤", "missing_info": "遺漏重點", "bad_citation": "引用不對或找不到依據",
    "unclear": "說明不清楚", "too_slow": "等太久", "other": "其他",
}
RATINGS = ("up", "down")


class FeedbackError(ValueError):
    pass


def _dir(root: Path) -> Path:
    return Path(root) / "feedback"


def snapshot(value: dict[str, Any]) -> dict[str, Any]:
    """What to remember of a finished task (the task result dict)."""
    answer = value.get("answer_main") or value.get("answer") or ""
    summary = (value.get("grounding") or {}).get("summary") or {}
    return {
        "question": str(value.get("question") or "")[:500], "answer_start": str(answer)[:800],
        "cited": [str(c.get("source") or c.get("revision_id") or "")[:160] for c in (value.get("citations") or [])[:8]],
        "tools": [str(t.get("tool")) for t in (value.get("trace") or [])][:30], "stop_reason": value.get("stop_reason"),
        "model": value.get("model"), "package_id": value.get("package_id"), "elapsed_ms": value.get("elapsed_ms"),
        "grounding": {k: summary.get(k) for k in ("claims", "claims_cited", "claims_tool_data", "values", "values_not_found", "claims_source_mismatch") if k in summary},
    }


def save(root: Path, task_id: str, owner: dict[str, Any], rating: str, reasons: list[str], comment: str, value: dict[str, Any]) -> dict[str, Any]:
    if not TASK_ID.match(str(task_id)):
        raise FeedbackError("task id")
    if rating not in RATINGS:
        raise FeedbackError("rating")
    reasons = [r for r in dict.fromkeys(reasons or []) if r in REASONS] if rating == "down" else []
    record = {"task_id": task_id, "rated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rating": rating, "reasons": reasons,
              "comment": str(comment or "").strip()[:COMMENT_CHARS], "owner": {"user_id": owner.get("user_id"), "instance_id": owner.get("instance_id")},
              **snapshot(value)}
    folder = _dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{task_id}.json"
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return {"task_id": task_id, "rating": rating, "reasons": reasons}


def summarize(root: Path, days: int = 30) -> dict[str, Any]:
    """Counts only -- no question or answer text leaves the data folder through this."""
    folder = _dir(root)
    since = time.time() - days * 86400
    up = down = 0
    by_reason: dict[str, int] = {}
    for path in folder.glob("*.json") if folder.is_dir() else []:
        try:
            if path.stat().st_mtime < since:
                continue
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("rating") == "up":
            up += 1
        elif record.get("rating") == "down":
            down += 1
            for reason in record.get("reasons") or []:
                by_reason[reason] = by_reason.get(reason, 0) + 1
    return {"days": days, "up": up, "down": down, "total": up + down, "down_reasons": [{"key": k, "label": REASONS.get(k, k), "count": n} for k, n in sorted(by_reason.items(), key=lambda kv: -kv[1])]}
