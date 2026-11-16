"""A slide deck written onto the company template (a ``.potx`` such as Askey Template.potx).

The logo, footer, colours and fonts come from the template's slide master and layouts; this module only chooses a layout for each page and
fills its placeholders. The language model never sees the file: it fills the ``ExportSpec`` (optionally naming a ``layout`` per section) and
this is the deterministic builder, so the same spec gives the same deck.

The template file is not part of the repository (it carries the company logo). ``KM_EXPORT_PPTX_TEMPLATE`` names it; without it
``config/templates/askey.potx`` is used. When the file is missing ``available()`` is False and the plain builder is used instead.
"""
from __future__ import annotations

import copy
import datetime
import io
import math
import os
import re
import zipfile
from functools import lru_cache
from pathlib import Path

from .spec import DISCLAIMER, ExportSpec, Section

DEFAULT_TEMPLATE = Path(__file__).resolve().parents[2] / "config" / "templates" / "askey.potx"
# Layout names inside the Askey template (looked up by name, so the order of layouts may change).
L_COVER, L_BODY, L_CHAPTER, L_TWO, L_COMPARE, L_CLOSING = "First", "Title and object", "Chapter title", "Two objects", "Comparison", "Thank you"

BODY_PT, COL_PT, TABLE_PT, SOURCE_PT = 18, 16, 12, 9
BODY_COLS, COL_COLS = 70, 36        # usable half-width characters per line (a CJK character counts 2)
BODY_BUDGET = 4.15                  # inches of body height before the sources line
LINE_FACTOR, GAP_IN = 1.3, 0.09
MAX_AGENDA = 10


def template_path() -> Path:
    return Path(os.environ.get("KM_EXPORT_PPTX_TEMPLATE") or DEFAULT_TEMPLATE)


def available() -> bool:
    return template_path().is_file()


def _control_free(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


# ------------------------------------------------------------------ opening the template

@lru_cache(maxsize=2)
def _template_bytes(path: str, mtime: float) -> bytes:
    """A .potx is a presentation whose main part has the template content type, which python-pptx refuses; make it a plain presentation."""
    raw = Path(path).read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info.filename)
            if info.filename == "[Content_Types].xml":
                data = data.replace(b"presentationml.template.main+xml", b"presentationml.presentation.main+xml")
            zout.writestr(info, data)
    return out.getvalue()


def _open():
    from pptx import Presentation
    path = template_path()
    prs = Presentation(io.BytesIO(_template_bytes(str(path), path.stat().st_mtime)))
    ids = prs.slides._sldIdLst          # the template's sample slides (charts, SmartArt, org chart) are not part of the output
    for sld in list(ids):
        prs.part.drop_rel(sld.rId)
        ids.remove(sld)
    return prs


# ------------------------------------------------------------------ measuring text (no rendering here: estimates, tuned on the Askey layouts)

def _width(text: str) -> int:
    return sum(2 if ord(c) > 0x2E7F else 1 for c in text)


def _lines(text: str, cols: int) -> int:
    return max(1, math.ceil(_width(text) / cols))


def _cost(text: str, cols: int, pt: int) -> float:
    return _lines(text, cols) * pt * LINE_FACTOR / 72 + GAP_IN


def _pieces(text: str, cols: int, pt: int, budget: float) -> list[str]:
    """One point taller than a whole page is cut at sentence ends (or, failing that, by length) so it never overflows."""
    if _cost(text, cols, pt) <= budget:
        return [text]
    parts = [p for p in re.split(r"(?<=[。；;！？!?])\s*|(?<=\.)\s+", text) if p]
    out, cur = [], ""
    for part in parts or [text]:
        while _cost(part, cols, pt) > budget:       # a single sentence that is still too long
            take = max(10, int(budget / (pt * LINE_FACTOR / 72) * cols / 2))
            out.append(part[:take])
            part = part[take:]
        if cur and _cost(cur + part, cols, pt) > budget:
            out.append(cur)
            cur = ""
        cur += part
    if cur:
        out.append(cur)
    return out


def _pages(points: list[str], cols: int, pt: int, budget: float = BODY_BUDGET, columns: int = 1) -> list[list[list[str]]]:
    """Fill pages greedily. Each page is a list of ``columns`` lists of points."""
    pages: list[list[list[str]]] = []
    page: list[list[str]] = [[] for _ in range(columns)]
    col, used = 0, 0.0
    for text in [q for p in points for q in _pieces(p, cols, pt, budget)]:
        c = _cost(text, cols, pt)
        if used + c > budget and (page[col] or col):
            if col + 1 < columns:
                col, used = col + 1, 0.0
            else:
                pages.append(page)
                page, col, used = [[] for _ in range(columns)], 0, 0.0
        page[col].append(text)
        used += c
    if any(page):
        pages.append(page)
    return pages


# ------------------------------------------------------------------ writing placeholders

def _layout(prs, name: str):
    for layout in prs.slide_layouts:
        if layout.name == name:
            return layout
    raise KeyError(f"template has no layout named {name!r}")


def _fill(placeholder, lines: list[str], size: int | None = None, *, bold: bool | None = None) -> None:
    frame = placeholder.text_frame
    frame.clear()
    for i, line in enumerate(lines):
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        run = p.add_run()
        run.text = _control_free(line)
        if size:
            run.font.size = _pt(size)
        if bold is not None:
            run.font.bold = bold


def _pt(n):
    from pptx.util import Pt
    return Pt(n)


def _number(slide, layout) -> None:
    """python-pptx does not copy the slide-number placeholder from the layout; do it so pages are numbered like the template's own."""
    for shape in layout.placeholders:
        if "sldNum" in shape._element.xml[:600]:
            slide.shapes._spTree.append(copy.deepcopy(shape._element))
            return


def _slide(prs, name: str):
    layout = _layout(prs, name)
    slide = prs.slides.add_slide(layout)
    _number(slide, layout)
    return slide


def _drop(shape) -> None:
    shape._element.getparent().remove(shape._element)


def _sources(slide, prs, sources: list[str]) -> None:
    if not sources:
        return
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches
    box = slide.shapes.add_textbox(Inches(0.89), Inches(5.82), Inches(8.8), Inches(0.3))
    box.text_frame.word_wrap = True
    box.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
    run = box.text_frame.paragraphs[0].add_run()
    run.text = _control_free(("來源：" + "；".join(sources))[:170])
    run.font.size, run.font.color.rgb = _pt(SOURCE_PT), RGBColor(0x59, 0x57, 0x57)


def _title(slide, heading: str, part: int, parts: int) -> None:
    slide.shapes.title.text_frame.text = _control_free(heading + (f"（{part}/{parts}）" if parts > 1 else ""))


# ------------------------------------------------------------------ pages

def _body_pages(prs, heading: str, points: list[str], sources: list[str], last_has_sources: bool) -> None:
    pages = _pages(points, BODY_COLS, BODY_PT)
    for i, page in enumerate(pages, 1):
        slide = _slide(prs, L_BODY)
        _title(slide, heading, i, len(pages))
        _fill(slide.placeholders[1], page[0], BODY_PT)
        if i == len(pages) and last_has_sources:
            _sources(slide, prs, sources)


def _balanced(items: list[str]) -> list[list[str]]:
    """Split one page's points into two columns of about equal height (a short list would otherwise all pile up in the left one)."""
    costs = [_cost(t, COL_COLS, COL_PT) for t in items]
    best = min(range(len(items) + 1), key=lambda k: max(sum(costs[:k]), sum(costs[k:])))
    return [items[:best], items[best:]]


def _two_column_pages(prs, heading: str, points: list[str], sources: list[str], last_has_sources: bool) -> None:
    pages = _pages(points, COL_COLS, COL_PT, columns=2)
    pages = [_balanced(page[0] + page[1]) for page in pages]
    for i, page in enumerate(pages, 1):
        slide = _slide(prs, L_TWO)
        _title(slide, heading, i, len(pages))
        for idx, lines in ((11, page[0]), (12, page[1])):
            ph = slide.placeholders[idx]
            if lines:
                _fill(ph, lines, COL_PT)
            else:
                _drop(ph)
        if i == len(pages) and last_has_sources:
            _sources(slide, prs, sources)


def _row_cost(row: list[str], widths: list[float]) -> float:
    lines = max(_lines(cell, max(6, int(w / 0.12))) for cell, w in zip(row, widths))
    return lines * TABLE_PT * LINE_FACTOR / 72 + 0.14


def _table_pages(prs, heading: str, table, sources: list[str]) -> None:
    from pptx.util import Inches
    table = table.square()
    n = len(table.columns)
    probe = next(ph for ph in _layout(prs, L_BODY).placeholders if ph.placeholder_format.idx == 1)   # by idx (indexing a layout's placeholders is by position)
    left, top, width = probe.left, probe.top, probe.width
    weights = [max(6, max(_width(c) for c in [table.columns[i]] + [r[i] for r in table.rows])) for i in range(n)]
    weights = [min(w, 60) for w in weights]
    total = sum(weights)
    widths_in = [width / 914400 * w / total for w in weights]
    groups, cur, used = [], [], _row_cost(table.columns, widths_in)
    head_cost = used
    for row in table.rows:
        c = _row_cost(row, widths_in)
        if cur and used + c > BODY_BUDGET:
            groups.append(cur)
            cur, used = [], head_cost
        cur.append(row)
        used += c
    groups.append(cur)
    for g, rows in enumerate(groups, 1):
        slide = _slide(prs, L_BODY)
        _title(slide, heading, g, len(groups))
        _drop(slide.placeholders[1])
        shape = slide.shapes.add_table(len(rows) + 1, n, left, top, width, Inches(0.4) * (len(rows) + 1))
        for c in range(n):
            shape.table.columns[c].width = int(width * weights[c] / total)
        for r, values in enumerate([table.columns] + rows):
            for c, value in enumerate(values):
                cell = shape.table.cell(r, c)
                cell.text = _control_free(value)
                for p in cell.text_frame.paragraphs:
                    for run in p.runs:
                        run.font.size = _pt(TABLE_PT)
        if g == len(groups):
            _sources(slide, prs, sources)


def _compare_pages(prs, heading: str, table, sources: list[str]) -> None:
    table = table.square()
    rows = table.rows
    pages = _pages([r[0] for r in rows], 30, 14, 3.3)           # pages are decided on the longer of the two columns
    start = 0
    chunks = []
    for page in pages:
        k = len(page[0])
        chunks.append(rows[start:start + k])
        start += k
    for i, chunk in enumerate(chunks, 1):
        slide = _slide(prs, L_COMPARE)
        _title(slide, heading, i, len(chunks))
        _fill(slide.placeholders[1], [table.columns[0]], None)
        _fill(slide.placeholders[14], [table.columns[1]], None)
        _fill(slide.placeholders[11], [r[0] for r in chunk], 14)
        _fill(slide.placeholders[15], [r[1] for r in chunk], 14)
        if i == len(chunks):
            _sources(slide, prs, sources)


def _section(prs, section: Section, spec: ExportSpec) -> None:
    heading = section.heading or spec.title
    points = [*section.paragraphs, *section.bullets]
    table = section.table if section.table and section.table.usable() else None
    layout = section.layout

    if layout == "chapter":
        slide = _slide(prs, L_CHAPTER)
        slide.shapes.title.text_frame.text = _control_free(heading)
        sub = points.pop(0)[:140] if points else ""
        if sub:
            _fill(slide.placeholders[1], [sub], None)
        else:
            _drop(slide.placeholders[1])
        layout = "bullets"

    if layout == "comparison" and table and len(table.columns) == 2:
        _compare_pages(prs, heading, table, section.sources)
        if points:
            _body_pages(prs, heading, points, section.sources, False)
        return
    if points:
        writer = _two_column_pages if layout == "two_column" else _body_pages
        writer(prs, heading, points, section.sources, table is None)
    if table:
        _table_pages(prs, heading, table, section.sources)
    if not points and not table and section.layout != "chapter":
        slide = _slide(prs, L_BODY)
        _title(slide, heading, 1, 1)
        _drop(slide.placeholders[1])
        _sources(slide, prs, section.sources)


def build(spec: ExportSpec) -> bytes:
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches
    prs = _open()

    cover = prs.slides.add_slide(_layout(prs, L_COVER))
    cover.shapes.title.text_frame.text = _control_free(spec.title)
    lines = [spec.subtitle] if spec.subtitle else []
    lines.append(datetime.date.today().strftime("%Y/%m/%d"))
    lines.append(DISCLAIMER)
    _fill(cover.placeholders[1], lines, 14)
    for p, size in zip(cover.placeholders[1].text_frame.paragraphs, [14] * (len(lines) - 2) + [12, 10]):
        for run in p.runs:
            run.font.size = _pt(size)

    headings = [s.heading or spec.title for s in spec.sections]
    if 3 <= len(headings) <= MAX_AGENDA:
        agenda = _slide(prs, L_BODY)
        agenda.shapes.title.text_frame.text = "目錄"
        _fill(agenda.placeholders[1], headings, BODY_PT)

    for section in spec.sections:
        _section(prs, section, spec)

    end = prs.slides.add_slide(_layout(prs, L_CLOSING))
    note = end.shapes.add_textbox(Inches(0.88), Inches(3.7), Inches(9.9), Inches(0.4))
    note.text_frame.word_wrap = True
    note.text_frame.paragraphs[0].alignment = PP_ALIGN.LEFT
    run = note.text_frame.paragraphs[0].add_run()
    run.text = DISCLAIMER
    run.font.size, run.font.color.rgb = _pt(10), RGBColor(0x59, 0x57, 0x57)

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
