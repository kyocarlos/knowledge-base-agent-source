"""Group Wi-Fi8 segments into retrieval chunks without dropping any text.

Unlike the generic Markdown chunker, short segments are merged, never discarded,
and every chunk keeps the document title and its source locations.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Iterable

POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "km/wifi8/chunk")


def _group_key(segment: dict[str, Any]) -> tuple:
    location = segment.get("location") or {}
    kind = location.get("type") or segment.get("kind")
    if kind == "paragraph":
        return (segment["revision_id"], kind)
    return (segment["revision_id"], kind,
            location.get("page") or location.get("slide") or location.get("sheet") or location.get("table") or "")


def location_label(location: dict[str, Any]) -> str:
    kind = location.get("type")
    if kind == "page":
        return f"第 {location.get('page')} 頁"
    if kind in {"slide", "slide_table", "slide_notes"}:
        return f"投影片 {location.get('slide')}" + (" 備註" if kind == "slide_notes" else "")
    if kind == "worksheet":
        return f"工作表 {location.get('sheet')}" + (f" 第 {location['row']} 列" if location.get("row") else "")
    if kind == "table":
        return f"表格 {location.get('table')}" + (f" 第 {location['row']} 列" if location.get("row") else "")
    if kind == "paragraph":
        return f"第 {location.get('paragraph')} 段"
    return ""


def build_chunks(documents: Iterable[dict[str, Any]], segments: Iterable[dict[str, Any]], *, max_chars: int) -> list[dict[str, Any]]:
    titles = {d["revision_id"]: d.get("title") or d["revision_id"] for d in documents}
    chunks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    key = None

    def close() -> None:
        if current and current["parts"]:
            text = "\n".join(current["parts"]).strip()
            if text:
                chunks.append({**current, "text": text})

    for segment in sorted(segments, key=lambda s: (s["revision_id"], int(s["ordinal"]))):
        text = str(segment.get("text") or "").strip()
        if not text:
            continue
        segment_key = _group_key(segment)
        size = sum(len(p) + 1 for p in current["parts"]) if current else 0
        if current is None or segment_key != key or size + len(text) > max_chars:
            close()
            key = segment_key
            current = {"revision_id": segment["revision_id"], "parts": [], "segment_ids": [], "locations": []}
        # Oversized single segments are kept whole in one chunk; they are never truncated away.
        current["parts"].append(text)
        current["segment_ids"].append(segment["segment_id"])
        current["locations"].append(segment.get("location") or {})
    close()

    seen: dict[tuple[str, str], int] = {}
    ordinals: dict[str, int] = {}
    result = []
    for chunk in chunks:
        rid = chunk["revision_id"]
        content_hash = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
        occurrence = seen.get((rid, content_hash), 0)
        seen[(rid, content_hash)] = occurrence + 1
        ordinals[rid] = ordinals.get(rid, 0) + 1
        first, last = chunk["locations"][0], chunk["locations"][-1]
        label = location_label(first)
        if last != first and location_label(last) != label:
            label = f"{label}～{location_label(last)}"
        title = titles.get(rid, rid)
        result.append({
            # Content-addressed identity lets a later package reuse unchanged vectors.
            "point_id": str(uuid.uuid5(POINT_NAMESPACE, f"{rid}/{content_hash}/{occurrence}")),
            "revision_id": rid,
            "ordinal": ordinals[rid],
            "segment_ids": chunk["segment_ids"],
            "location": first,
            "location_label": label,
            "content_hash": content_hash,
            "text": chunk["text"],
            "embed_text": f"{title}\n{label}\n{chunk['text']}",
        })
    return result
