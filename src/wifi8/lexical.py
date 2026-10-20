"""BM25 sparse vectors for Qdrant full-text retrieval in the WiFi zone.

Qdrant applies the IDF part (sparse vector ``modifier=idf``); the term-frequency
part is computed here with a configured average length, so a chunk's vector only
depends on its own text and can be shared between packages unchanged.

Tokens: Latin/digit terms (plus their parts, so "Wi-Fi" also matches "wifi"/"fi"),
and CJK character bigrams, which match 2-character words and longer phrases alike.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+/_-]*|[㐀-鿿]+")
_CJK = re.compile(r"[㐀-鿿]+")
_PARTS = re.compile(r"[.+/_-]+")
STOPWORDS = frozenset({
    "the", "and", "for", "what", "how", "with", "from", "that", "this", "are", "is", "of", "in", "to", "a", "an",
    "什麼", "如何", "哪些", "請問", "說明", "介紹", "相關", "資料", "文件", "是否", "可以", "以及", "還有", "知識專區",
})
_CJK_STOPWORDS = sorted((w for w in STOPWORDS if _CJK.fullmatch(w)), key=len, reverse=True)
K1, B = 1.2, 0.75

# Short names that tell sibling documents apart (PF1 Report / EE1 Report). In a title they are upper-case letters then
# digits, so version labels (v1, Rev2, Part2) are not names; a user may type them in any case.
_TITLE_CODE = re.compile(r"(?<![A-Za-z0-9-])[A-Z]{2,5}\d{1,3}(?![A-Za-z0-9])")
_TEXT_CODE = re.compile(r"(?<![A-Za-z0-9-])[A-Za-z]{2,5}\d{1,3}(?![A-Za-z0-9])")


def title_codes(title: str) -> set[str]:
    return {c.casefold() for c in _TITLE_CODE.findall(str(title or ""))}


def text_codes(text: str) -> set[str]:
    return {c.casefold() for c in _TEXT_CODE.findall(str(text or ""))}


def _latin(token: str) -> list[str]:
    token = token.casefold().rstrip(".+/_-")
    if not token or token in STOPWORDS:
        return []
    parts = [p for p in _PARTS.split(token) if p and p not in STOPWORDS]
    joined = "".join(parts)
    return list(dict.fromkeys([token, *(parts if len(parts) > 1 else []), *([joined] if len(parts) > 1 else [])]))


def _cjk(run: str) -> list[str]:
    if len(run) == 1:
        return [run]
    return [run[i:i + 2] for i in range(len(run) - 1)]


def tokens(text: str) -> list[str]:
    out: list[str] = []
    for token in _TOKEN.findall(text or ""):
        out.extend(_cjk(token) if _CJK.fullmatch(token) else _latin(token))
    return out


def query_terms(query: str) -> list[str]:
    """Distinct query terms; CJK question words are removed before bigrams are formed."""
    text = query or ""
    for word in _CJK_STOPWORDS:
        text = text.replace(word, " ")
    return list(dict.fromkeys(t for t in tokens(text) if t not in STOPWORDS))


def term_index(term: str) -> int:
    return int.from_bytes(hashlib.blake2b(term.encode("utf-8"), digest_size=4).digest(), "big")


def document_vector(text: str, title: str = "", *, avg_tokens: float, title_weight: int = 2) -> tuple[list[int], list[float]]:
    counts = Counter(tokens(text))
    for term in tokens(title):
        counts[term] += title_weight
    length = sum(counts.values()) or 1
    norm = K1 * (1 - B + B * length / max(avg_tokens, 1.0))
    weights: dict[int, float] = {}
    for term, tf in counts.items():
        index = term_index(term)
        weights[index] = weights.get(index, 0.0) + tf * (K1 + 1) / (tf + norm)
    indices = sorted(weights)
    return indices, [weights[i] for i in indices]


EXPANSIONS_FILE_ENV = "KM_WIFI8_QUERY_EXPANSIONS_FILE"
DEFAULT_EXPANSIONS_FILE = Path(__file__).with_name("query_expansions.json")


def load_expansions() -> list[tuple[list[str], list[str]]]:
    """(when, add) rules; a missing or broken file means no expansion, never a failed search."""
    path = Path(os.getenv(EXPANSIONS_FILE_ENV) or DEFAULT_EXPANSIONS_FILE)
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))["expansions"]
        return [([str(w).casefold() for w in r["when"]], [str(a) for a in r["add"]]) for r in rules]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def _mentions(text: str, word: str) -> bool:
    if _CJK.search(word):
        return word in text
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text) is not None


def expanded_terms(query: str) -> list[str]:
    """Terms added to the full-text query for a question phrased differently from the documents (see query_expansions.json)."""
    text = (query or "").casefold()
    added = [a for when, add in load_expansions() if any(_mentions(text, w) for w in when) for a in add]
    return list(dict.fromkeys(t for a in added for t in tokens(a) if t not in STOPWORDS))


def query_vector(query: str) -> tuple[list[int], list[float]]:
    indices = sorted({term_index(t) for t in [*query_terms(query), *expanded_terms(query)]})
    return indices, [1.0] * len(indices)
