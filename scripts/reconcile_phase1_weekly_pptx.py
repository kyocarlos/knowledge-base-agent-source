#!/usr/bin/env python3
"""Reconcile the 17-slide W33 supervisor deck with evidence-backed metrics."""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE


METRIC_REPLACEMENTS = (
    (re.compile(r"94\s*%"), "85%"),
    (re.compile(r"96\s*%"), "87%"),
    (re.compile(r"21\.1\s*%"), "19.1%"),
    (re.compile(r"12\.7\s*%"), "11.5%"),
    (re.compile(r"90\s+passed", re.IGNORECASE), "83 passed（GitHub CI）"),
    (
        re.compile(r"WP1\s*(?:仍)?無\s*PR[／、, ]*review[／、, ]*merge", re.IGNORECASE),
        "WP1 已有 Draft acceptance PR #5；無獨立交付 PR／review／merge",
    ),
)

FORBIDDEN = (
    re.compile(r"94\s*%"),
    re.compile(r"96\s*%"),
    re.compile(r"21\.1\s*%"),
    re.compile(r"12\.7\s*%"),
    re.compile(r"90\s+passed", re.IGNORECASE),
)


def reconcile_text(value: str) -> str:
    value = value.replace("2026-08-12 17:00（Asia/Taipei）", "2026-08-12 17:00 Asia/Taipei")
    if re.search(r"(?:全計畫|整體計畫|全案).*進度", value) and "%" in value:
        value = re.sub(r"\d+(?:\.\d+)?\s*%", "11.5%", value)
    if re.search(r"Phase\s*1.*進度", value, re.IGNORECASE) and "%" in value:
        value = re.sub(r"\d+(?:\.\d+)?\s*%", "19.1%", value)
    for pattern, replacement in METRIC_REPLACEMENTS:
        value = pattern.sub(replacement, value)
    return value


def reconcile_paragraph(paragraph) -> int:
    before = paragraph.text
    after = reconcile_text(before)
    if after == before:
        return 0
    if paragraph.runs:
        paragraph.runs[0].text = after
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.text = after
    return 1


def walk_shapes(shapes):
    for shape in shapes:
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from walk_shapes(shape.shapes)


def reconcile_shape(shape) -> int:
    changes = 0
    if getattr(shape, "has_text_frame", False):
        for paragraph in shape.text_frame.paragraphs:
            changes += reconcile_paragraph(paragraph)
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            for cell in row.cells:
                for paragraph in cell.text_frame.paragraphs:
                    changes += reconcile_paragraph(paragraph)
    return changes


def shape_text(shape) -> list[str]:
    values: list[str] = []
    if getattr(shape, "has_text_frame", False):
        values.extend(p.text for p in shape.text_frame.paragraphs if p.text.strip())
    if getattr(shape, "has_table", False):
        for row in shape.table.rows:
            for cell in row.cells:
                values.extend(p.text for p in cell.text_frame.paragraphs if p.text.strip())
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--text-output", required=True, type=Path)
    parser.add_argument("--qa-output", required=True, type=Path)
    args = parser.parse_args()

    presentation = Presentation(args.input)
    if len(presentation.slides) != 17:
        raise SystemExit(f"expected 17 slides, found {len(presentation.slides)}")

    changed_paragraphs = 0
    all_text: list[str] = []
    out_of_bounds: list[dict[str, int]] = []
    for slide_number, slide in enumerate(presentation.slides, start=1):
        slide_lines: list[str] = []
        for shape in walk_shapes(slide.shapes):
            changed_paragraphs += reconcile_shape(shape)
            slide_lines.extend(shape_text(shape))
            if min(shape.left, shape.top) < 0 or shape.left + shape.width > presentation.slide_width or shape.top + shape.height > presentation.slide_height:
                out_of_bounds.append({"slide": slide_number, "shape_id": shape.shape_id})
        all_text.append(f"## Slide {slide_number}\n" + "\n".join(slide_lines))

    rendered_text = "\n\n".join(all_text)
    for pattern in FORBIDDEN:
        if pattern.search(rendered_text):
            raise SystemExit(f"forbidden unverified metric remains: {pattern.pattern}")
    for required in ("85%", "87%", "19.1%"):
        if required not in rendered_text:
            raise SystemExit(f"required reconciled value missing: {required}")
    if out_of_bounds:
        raise SystemExit(f"shapes outside slide bounds: {out_of_bounds}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.text_output.parent.mkdir(parents=True, exist_ok=True)
    args.qa_output.parent.mkdir(parents=True, exist_ok=True)
    if changed_paragraphs:
        presentation.save(args.output)
    else:
        shutil.copyfile(args.input, args.output)
    args.text_output.write_text(rendered_text + "\n", encoding="utf-8")
    args.qa_output.write_text(
        json.dumps(
            {
                "slides": 17,
                "reconciliation": "passed",
                "metrics": {"WP0": 85, "WP1": 87, "Phase 1": 19.1, "program": 11.5},
                "cutoff": "2026-08-12 17:00 Asia/Taipei",
                "out_of_bounds_shapes": 0,
                "forbidden_unverified_metrics": [],
                "program_metric_in_deck": "not displayed; canonical value remains 11.5% in JSON and Markdown",
                "cutoff_in_deck": "not displayed; canonical cutoff remains 2026-08-12 17:00 Asia/Taipei in Evidence, JSON and Markdown",
                "render_check": "pending",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
