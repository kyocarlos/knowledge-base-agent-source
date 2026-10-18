"""Query-focused excerpts of long chunks, shared by the agent tools and the reranker."""
from __future__ import annotations

import math
import re
from collections import Counter

from .lexical import query_terms, tokens


_SENTENCE = re.compile(r".+?(?:[。！？!?；;]|\.(?=\s)|\n|$)", re.S)


def excerpt(text: str, query: str, limit: int) -> tuple[str, bool]:
    """At most `limit` characters of `text`; when it is longer, keep the sentences that best
    match the query terms (rarer terms in this text weigh more), in their original order,
    marking skipped parts with "…". Without matching terms the head of the text is kept."""
    text = text or ""
    if len(text) <= limit:
        return text, False
    sentences = [m.group(0) for m in _SENTENCE.finditer(text) if m.group(0).strip()]
    terms = set(query_terms(query or ""))
    present = [terms & set(tokens(sentence)) for sentence in sentences]
    df = Counter(term for found in present for term in found)
    scores = [sum(1 + math.log(len(sentences) / df[t]) for t in found) for found in present]
    if not any(scores):
        return text[: max(0, limit - 1)] + "…", True
    chosen, used = set(), 0
    for i in sorted(range(len(sentences)), key=lambda i: (-scores[i], i)):
        if scores[i] <= 0:
            break
        if used + len(sentences[i]) + 1 <= limit:
            chosen.add(i)
            used += len(sentences[i]) + 1
    if not chosen:  # the best sentence alone is longer than the budget
        best = max(range(len(sentences)), key=lambda i: (scores[i], -i))
        return sentences[best].strip()[: max(0, limit - 2)] + "…", True
    for i in range(len(sentences)):  # fill the remaining budget with neighbouring context
        if i not in chosen and (i - 1 in chosen or i + 1 in chosen) and used + len(sentences[i]) + 1 <= limit:
            chosen.add(i)
            used += len(sentences[i]) + 1
    parts, previous = [], -1
    for i in sorted(chosen):
        if i != previous + 1:
            parts.append("…")
        parts.append(sentences[i].strip())
        previous = i
    if previous != len(sentences) - 1:
        parts.append("…")
    return "\n".join(parts), True


def table_excerpt(markdown: str, query: str, limit: int) -> tuple[str, bool]:
    """Excerpt of a Markdown table that always keeps its header (and a "（續上表）" note) and picks
    the rows that best match the query."""
    if len(markdown) <= limit:
        return markdown, False
    lines = markdown.split("\n")
    head_size = 3 if lines and lines[0].startswith("（續上表）") else 2
    head = "\n".join(lines[:head_size])
    rows, cut = excerpt("\n".join(lines[head_size:]), query, max(0, limit - len(head) - 1))
    return head + "\n" + rows, cut
