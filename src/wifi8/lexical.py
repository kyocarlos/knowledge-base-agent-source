"""BM25 sparse vectors for Qdrant full-text retrieval in the WiFi zone.

Qdrant applies the IDF part (sparse vector ``modifier=idf``); the term-frequency
part is computed here with a configured average length, so a chunk's vector only
depends on its own text and can be shared between packages unchanged.

Tokens: Latin/digit terms (plus their parts, so "Wi-Fi" also matches "wifi"/"fi"),
and CJK character bigrams, which match 2-character words and longer phrases alike.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+/_-]*|[㐀-鿿]+")
_CJK = re.compile(r"[㐀-鿿]+")
_PARTS = re.compile(r"[.+/_-]+")
STOPWORDS = frozenset({
    "the", "and", "for", "what", "how", "with", "from", "that", "this", "are", "is", "of", "in", "to", "a", "an",
    "什麼", "如何", "哪些", "請問", "說明", "介紹", "相關", "資料", "文件", "是否", "可以", "以及", "還有", "知識專區",
})
_CJK_STOPWORDS = sorted((w for w in STOPWORDS if _CJK.fullmatch(w)), key=len, reverse=True)
K1, B = 1.2, 0.75


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


def query_vector(query: str) -> tuple[list[int], list[float]]:
    indices = sorted({term_index(t) for t in query_terms(query)})
    return indices, [1.0] * len(indices)
