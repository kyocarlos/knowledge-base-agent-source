"""Usage ledger for a metered external LLM account (today: the SAM compute centre's ModaOne grant).

There is no API to read ModaOne's live balance — only a daily notification email and a login portal (aipower.dginfra.gov.tw, needs a
company certificate). This file tracks what KM itself has actually sent through such an account (from each real call's own token
counts, never estimated), in points (1 point = 100,000 input+output tokens, per the SAM notice). It is **not the official balance**:
other use of the same account outside KM, if any, is not counted, and a call KM made while this file could not be written is lost.

Shared across every KM process that may call the account — the web app and the export service both record here — through one host
file, so a container restart does not reset the count. ``record`` never raises: a usage write must not break an answer.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)
POINT_TOKENS = 100_000  # SAM notice: 1 point = 100,000 input or output tokens
DEFAULT_FILE = Path(__file__).resolve().parents[2] / "config" / "llm_usage.json"
_lock = threading.Lock()


def _file() -> Path:
    return Path(os.environ.get("KM_LLM_USAGE_FILE") or DEFAULT_FILE)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        logger.warning("LLM usage ledger %s is unreadable, starting from empty (%s)", path, type(exc).__name__)
        return {}


def record(account: str, prompt_tokens: int, completion_tokens: int) -> None:
    prompt_tokens, completion_tokens = max(0, int(prompt_tokens or 0)), max(0, int(completion_tokens or 0))
    if not account or (prompt_tokens == 0 and completion_tokens == 0):
        return
    path = _file()
    try:
        with _lock:
            data = _read(path)
            entry = data.setdefault(account, {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0})
            entry["prompt_tokens"] += prompt_tokens
            entry["completion_tokens"] += completion_tokens
            entry["calls"] += 1
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
    except OSError:
        logger.warning("could not write LLM usage ledger %s", path, exc_info=True)


def summary(account: str, granted_points: float | None = None) -> dict:
    """KM's own running total for ``account``, in points and tokens. ``pointsRemaining`` is included only when ``granted_points``
    is known (config/llm_profiles.json "accounts"."<account>"."granted_points"); without it there is no total to subtract from."""
    entry = _read(_file()).get(account) or {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    tokens = entry["prompt_tokens"] + entry["completion_tokens"]
    points = tokens / POINT_TOKENS
    out = {"tokensUsed": tokens, "pointsUsed": round(points, 2), "callsRecorded": entry["calls"], "official": False}
    if granted_points is not None:
        out["grantedPoints"] = granted_points
        out["pointsRemaining"] = round(max(0.0, granted_points - points), 2)
    return out


def reset(account: str) -> None:
    """For tests, or an explicit admin action — never called from an answer path."""
    path = _file()
    with _lock:
        data = _read(path)
        if account in data:
            del data[account]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
