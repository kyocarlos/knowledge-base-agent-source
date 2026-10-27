"""Help for "which documents ..." questions: the filters a question already names, applied by code instead of left to the model's choice.

Recall of a list answer swings with whether the model happened to add ``publisher="arXiv"`` or a larger ``limit`` (golden set L01: 5 of 9 papers without the
filter, 9 of 9 with it). A publisher or document type that the question itself names is applied when the model passed no filter; the result says so, and
``all_documents`` switches it off. Only values the zone really has are used, and a question that names two publishers is a comparison and is left alone.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

HINTS_FILE = Path(__file__).with_name("list_hints.json")
MIN_NAME_CHARS = 3

LIST_PROMPT = """
列舉題（本次已啟用列舉輔助）：把 find_documents 回傳、且與題目相符的文件全部列出，不要只挑代表性的幾份，並依相關度排序。
- 問「討論、主要在談、大量討論」：discusses=true 的文件（程式依相符段落數判定）一定要全部列出；discusses=false 的只在確實相關時才列。
- 問「提到、涉及、有哪些…提到」：matching_chunks 至少 1 的文件都算，全部列出（可依 matching_chunks 由多到少排序）。
- inferred_filters 是程式依題目套用的發布者或文件類型；more_available 為 true 時，先提高 limit（最多 30）或用更精確的條件再查一次，再作答。
- 清單末尾註明依據的是本次檢索結果，可能未涵蓋全部。"""


@lru_cache(maxsize=1)
def hints() -> dict[str, Any]:
    return json.loads(HINTS_FILE.read_text(encoding="utf-8"))


def discusses_threshold(top_chunks: int, data: dict[str, Any] | None = None) -> int:
    """How many matching chunks make a document "about" the topic: a floor, and a share of the best document's count (a topic with one dominant paper
    needs more than a floor to tell the others apart)."""
    cfg = (data or hints()).get("discusses") or {}
    return max(int(cfg.get("min_chunks", 3)), int(float(top_chunks) * float(cfg.get("ratio", 0.05)) + 0.5))


def _mentions(text: str, name: str) -> bool:
    """Whole-token, case-insensitive: "Intel" is not in "intelligent"; CJK text has no spaces, so only Latin edges are checked."""
    return bool(re.search(r"(?<![A-Za-z0-9])" + re.escape(name.casefold()) + r"(?![A-Za-z0-9])", text.casefold()))


def infer_filters(question: str, publishers: set[str], roles: set[str], data: dict[str, Any] | None = None) -> dict[str, Any]:
    """{"publisher": name} and/or {"document_roles": [..]} that the question names; empty when nothing (or something ambiguous) is named."""
    data, text = data or hints(), str(question or "")
    named = sorted({p for p in publishers if len(p) >= MIN_NAME_CHARS and _mentions(text, p)}, key=len, reverse=True)
    # "Wi-Fi NOW" contains "Wi-Fi"; a longer name that covers a shorter one wins, otherwise two names mean a comparison.
    named = [n for n in named if not any(n != m and n.casefold() in m.casefold() for m in named)]
    found: dict[str, Any] = {}
    if len(named) == 1:
        found["publisher"] = named[0]
    wanted: list[str] = []
    for phrase, values in (data.get("role_aliases") or {}).items():
        if _mentions(text, phrase):
            wanted += [v for v in values if v in roles and v not in wanted]
    if wanted:
        found["document_roles"] = wanted
    return found
