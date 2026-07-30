"""Shared compare query helpers."""

from __future__ import annotations

import re
from typing import Callable

COMPARE_QUERY_RE = re.compile(r"(比較|差異|不同|對比|比對|\bvs\b|\bversus\b)", re.IGNORECASE)


def normalize_text(value: object) -> str:
    return str(value or "").strip()


def is_compare_like_query(text: object) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False
    return bool(COMPARE_QUERY_RE.search(normalized))


def should_prefer_wifi_compare(text: object, is_wifi_specific_query: Callable[[object], bool] | None) -> bool:
    if not callable(is_wifi_specific_query):
        return False
    return is_compare_like_query(text) and bool(is_wifi_specific_query(text))
