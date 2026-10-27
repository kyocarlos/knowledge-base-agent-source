"""Conversation memory for the WiFi agent: recent turns verbatim, older turns condensed by code (no model call, so no extra wait and nothing invented).

A condensed exchange keeps what was asked, the opening of the conclusion and the documents the answer relied on -- enough for a follow-up such as
"那第二份文件呢" or "剛才說的 NPCA" to be resolved. The page sends the turns (and, per assistant turn, the titles it cited); nothing is stored server side.
"""
from __future__ import annotations

import re
from typing import Any

RECENT_TURNS = 6          # messages kept verbatim
TURN_CHARS = 2000         # per verbatim message
QUESTION_CHARS = 160
CONCLUSION_CHARS = 220
SOURCES_PER_EXCHANGE = 3
SOURCE_CHARS = 90
DIGEST_CHARS = 3000
DIGEST_HEADER = "先前對話摘要（較早的輪次，已由程式壓縮；細節請重新查證，不要把摘要當作新的查證結果）："

_MARKDOWN = re.compile(r"^\s{0,3}#{1,6}\s*|\*\*|`|\[S\d+\]|\[G\d+\]")


def _one_line(text: str, limit: int) -> str:
    flat = re.sub(r"\s+", " ", _MARKDOWN.sub("", str(text or ""))).strip()
    flat = re.sub(r"^結論[:：]?\s*", "", flat)
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


def _exchanges(turns: list[dict[str, Any]]) -> list[tuple[str, str, list[str]]]:
    """(question, conclusion, sources) per user turn; an unanswered question has an empty conclusion."""
    out: list[tuple[str, str, list[str]]] = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        if turn.get("role") == "user":
            out.append((_one_line(turn.get("content") if isinstance(turn.get("content"), str) else "", QUESTION_CHARS), "", []))
        elif turn.get("role") == "assistant" and out:
            question, _, _ = out[-1]
            sources = [_one_line(s, SOURCE_CHARS) for s in (turn.get("sources") or [])[:SOURCES_PER_EXCHANGE] if isinstance(s, str) and s.strip()]
            content = turn.get("content")
            out[-1] = (question, _one_line(content, CONCLUSION_CHARS) if isinstance(content, str) else "", sources)
    return out


def digest(older: list[dict[str, Any]], limit: int = DIGEST_CHARS) -> str:
    """The condensed older turns, newest exchanges first when they do not all fit; empty when there is nothing to condense."""
    lines = [f"- 問：{q}" + (f"｜答：{a}" if a else "｜（未取得回答）") + (f"｜來源：{'、'.join(s)}" if s else "") for q, a, s in _exchanges(older)]
    kept: list[str] = []
    used = len(DIGEST_HEADER)
    for line in reversed(lines):
        if used + len(line) + 1 > limit:
            break
        kept.append(line)
        used += len(line) + 1
    if not kept:
        return ""
    omitted = len(lines) - len(kept)
    return DIGEST_HEADER + ("\n（更早的 %d 輪未列入）" % omitted if omitted else "") + "\n" + "\n".join(reversed(kept))


def history_messages(history: list[dict[str, Any]] | None, *, recent: int = RECENT_TURNS, condense: bool = True) -> list[dict[str, str]]:
    """Chat messages for the model: [digest of older turns] + the last ``recent`` turns verbatim. ``condense=False`` is the old behaviour (older turns dropped)."""
    turns = [t for t in (history or []) if isinstance(t, dict) and t.get("role") in {"user", "assistant"} and isinstance(t.get("content"), str)]
    older, latest = turns[:-recent] if recent else turns, turns[-recent:] if recent else []
    # A window that starts with an assistant turn would show an answer without its question: move that question's turn into the digest side.
    if latest and latest[0]["role"] == "assistant" and older:
        latest, older = [older[-1], *latest], older[:-1]
    messages: list[dict[str, str]] = []
    summary = digest(older) if condense else ""
    if summary:
        messages.append({"role": "system", "content": summary})
    messages += [{"role": t["role"], "content": t["content"][:TURN_CHARS]} for t in latest]
    return messages
