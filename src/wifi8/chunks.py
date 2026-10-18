"""Group Wi-Fi8 segments into retrieval chunks without dropping any text.

Unlike the generic Markdown chunker, short segments are merged, never discarded,
and every chunk keeps the document title and its source locations.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Iterable

POINT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "km/wifi8/chunk")
# Bump when display_text changes: a package imported with an older version is imported again so the
# existing chunks get the new display text (identities and vectors are untouched).
DISPLAY_VERSION = 1
TABULAR = {"table", "slide_table", "worksheet"}


def _table_key(segment: dict[str, Any]) -> tuple:
    location = segment.get("location") or {}
    return (segment["revision_id"], location.get("type"), location.get("slide"), location.get("table"), location.get("sheet"))


def _cells(row: str) -> list[str]:
    return [cell.strip().replace("\n", " / ").replace("|", "／") for cell in row.split(" | ")]


def markdown_table(header: str, rows: list[str], *, continued: bool = False) -> str:
    """Rows extracted as "a | b | c" back into a Markdown table (the first row of the table is its header)."""
    head = _cells(header)
    body = [_cells(r) for r in rows]
    width = max([len(head)] + [len(r) for r in body])
    pad = lambda cells: cells + [""] * (width - len(cells))  # noqa: E731
    lines = ["| " + " | ".join(pad(head)) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(pad(r)) + " |" for r in body]
    return ("（續上表）\n" if continued else "") + "\n".join(lines)


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
    if kind == "image":
        return "圖片檔"
    return ""


IMAGE_MARK = "【圖片】"


def image_chunks(documents: Iterable[dict[str, Any]], images: Iterable[dict[str, Any]], texts: dict[str, str],
                 after: dict[str, int]) -> list[dict[str, Any]]:
    """One chunk per described figure, numbered after the text chunks of its document (``after``: revision_id -> last
    text ordinal) so text chunk identities and order never change. Figures without text (none, failed, decorative)
    are left out."""
    titles = {d["revision_id"]: d.get("title") or d["revision_id"] for d in documents}
    ordinals = dict(after)
    result = []
    for image in sorted(images, key=lambda i: (i["revision_id"], int(i["ordinal"]))):
        described = texts.get(image["image_id"], "")
        if not described:
            continue
        rid = image["revision_id"]
        place = location_label(image.get("location") or {})
        label = f"{place}・圖 {image['ordinal']}" if place and place != "圖片檔" else f"圖 {image['ordinal']}"
        caption = str(image.get("caption") or "").strip()
        text = "\n".join(part for part in (IMAGE_MARK + (caption or ""), described) if part).strip()
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        ordinals[rid] = ordinals.get(rid, 0) + 1
        result.append({
            "point_id": str(uuid.uuid5(POINT_NAMESPACE, f"{rid}/image/{image['image_id']}/{content_hash}")),
            "revision_id": rid,
            "ordinal": ordinals[rid],
            "segment_ids": [],
            "location": {**(image.get("location") or {}), "figure": image["ordinal"]},
            "location_label": label,
            "content_hash": content_hash,
            "text": text,
            "embed_text": f"{titles.get(rid, rid)}\n{label}\n{text}",
            "display_text": None,
            "image": {"id": image["image_id"], "extension": image["extension"],
                      "width": image.get("width"), "height": image.get("height")},
        })
    return result


def build_chunks(documents: Iterable[dict[str, Any]], segments: Iterable[dict[str, Any]], *, max_chars: int) -> list[dict[str, Any]]:
    titles = {d["revision_id"]: d.get("title") or d["revision_id"] for d in documents}
    segments = list(segments)
    # First row of every table / worksheet: the header shown again on chunks that continue a long table.
    headers: dict[tuple, str] = {}
    for segment in sorted(segments, key=lambda s: (s["revision_id"], int(s["ordinal"]))):
        location = segment.get("location") or {}
        if location.get("type") in TABULAR and str(segment.get("text") or "").strip():
            headers.setdefault(_table_key(segment), str(segment["text"]).strip())
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
            current = {"revision_id": segment["revision_id"], "parts": [], "segment_ids": [], "locations": [],
                       "table_key": _table_key(segment)}
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
        display = None
        if first.get("type") in TABULAR and any(" | " in part for part in chunk["parts"]):
            header = headers.get(chunk["table_key"])
            starts_table = header is not None and chunk["parts"][0] == header
            rows = chunk["parts"][1:] if starts_table else chunk["parts"]
            display = markdown_table(header or chunk["parts"][0], rows if header else chunk["parts"][1:],
                                     continued=bool(header) and not starts_table)
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
            # Display only: identity, BM25 and the dense vector keep using `text`.
            "display_text": display,
        })
    return result
