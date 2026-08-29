"""
圖片引用抽取共用工具。

將 Markdown / source metadata 中的 asset:// 引用統一抽取與正規化，
避免各模組各自維護不同的正則。
"""

from __future__ import annotations

import re
from typing import Iterable, List


IMAGE_REF_PATTERNS = (
    r"原圖引用[:：]\s*(\S+)",
    r"圖片資產[:：]\s*(\S+)",
    r"頁面快照引用[:：]\s*(\S+)",
    r"asset://(\S+)",
)


def normalize_asset_ref(ref: str) -> str:
    value = (ref or "").strip()
    if value.startswith("asset://"):
        value = value[len("asset://") :]
    return value.lstrip("/")


def extract_image_refs_from_text(content: str | None) -> List[str]:
    if not content:
        return []

    refs: List[str] = []
    for pattern in IMAGE_REF_PATTERNS:
        for match in re.findall(pattern, content):
            ref = normalize_asset_ref(str(match).strip())
            if ref and ref not in refs:
                refs.append(ref)
    return refs


def merge_image_refs(*values: Iterable[str] | None) -> List[str]:
    merged: List[str] = []
    for value in values:
        if not value:
            continue
        for ref in value:
            normalized = normalize_asset_ref(str(ref))
            if normalized and normalized not in merged:
                merged.append(normalized)
    return merged
