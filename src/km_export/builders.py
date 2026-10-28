"""Write an ``ExportSpec`` as a file. Pure functions: no network, no model, so the same spec always gives the same file."""
from __future__ import annotations

import csv
import html
import io
import re
import zipfile
from xml.sax.saxutils import escape as xml_escape

from .spec import DISCLAIMER, ExportSpec, Section

MEDIA_TYPES = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "md": "text/markdown; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
    "html": "text/html; charset=utf-8",
}
CJK_FONT = "Microsoft JhengHei"
BULLETS_PER_SLIDE = 6
ROWS_PER_SLIDE = 9


def safe_filename(title: str, extension: str) -> str:
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", title).strip(" .") or "export"
    return f"{stem[:80]}.{extension}"


def _control_free(text: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


# ------------------------------------------------------------------ markdown / csv / html

def build_markdown(spec: ExportSpec) -> bytes:
    lines = [f"# {spec.title}", ""]
    if spec.subtitle:
        lines += [f"_{spec.subtitle}_", ""]
    for section in spec.sections:
        if section.heading:
            lines += [f"## {section.heading}", ""]
        lines += [p + "\n" for p in section.paragraphs]
        lines += [f"- {b}" for b in section.bullets] + ([""] if section.bullets else [])
        table = section.table.square() if section.table and section.table.usable() else None
        if table:
            esc = lambda c: c.replace("|", "\\|")
            lines += ["| " + " | ".join(esc(c) for c in table.columns) + " |", "|" + " --- |" * len(table.columns)]
            lines += ["| " + " | ".join(esc(c) for c in row) + " |" for row in table.rows] + [""]
        if section.sources:
            lines += ["來源：", *[f"- {s}" for s in section.sources], ""]
    lines += ["---", f"_{DISCLAIMER}_", ""]
    return "\n".join(lines).encode("utf-8")


def build_csv(spec: ExportSpec) -> bytes:
    """One table per section, separated by a blank line and the section heading; sections without a table contribute their bullets."""
    out = io.StringIO()
    writer = csv.writer(out)
    for section in spec.sections:
        table = section.table.square() if section.table and section.table.usable() else None
        if not (table or section.bullets or section.paragraphs):
            continue
        if out.tell():
            writer.writerow([])
        writer.writerow([section.heading or spec.title])
        if table:
            writer.writerow(table.columns)
            writer.writerows(table.rows)
        else:
            writer.writerows([[t] for t in [*section.paragraphs, *section.bullets]])
    writer.writerow([])
    writer.writerow([DISCLAIMER])
    return ("﻿" + out.getvalue()).encode("utf-8")  # BOM so Excel reads the Chinese text correctly


def build_html(spec: ExportSpec) -> bytes:
    e = html.escape
    body = [f"<h1>{e(spec.title)}</h1>"]
    if spec.subtitle:
        body.append(f'<p class="sub">{e(spec.subtitle)}</p>')
    for section in spec.sections:
        if section.heading:
            body.append(f"<h2>{e(section.heading)}</h2>")
        body += [f"<p>{e(p)}</p>" for p in section.paragraphs]
        if section.bullets:
            body.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in section.bullets) + "</ul>")
        if section.table and section.table.usable():
            t = section.table.square()
            body.append("<table><thead><tr>" + "".join(f"<th>{e(c)}</th>" for c in t.columns) + "</tr></thead><tbody>"
                        + "".join("<tr>" + "".join(f"<td>{e(c)}</td>" for c in row) + "</tr>" for row in t.rows) + "</tbody></table>")
        if section.sources:
            body.append('<p class="src">來源：</p><ul class="src">' + "".join(f"<li>{e(s)}</li>" for s in section.sources) + "</ul>")
    body.append(f'<hr><p class="note">{e(DISCLAIMER)}</p>')
    style = ("body{font-family:'Microsoft JhengHei','Noto Sans TC',sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;line-height:1.7;color:#1b2a30}"
             "h1{font-size:1.7rem}h2{margin-top:1.8rem;border-bottom:1px solid #d6e0e3;padding-bottom:.2rem}.sub{color:#5a6b72}"
             "table{border-collapse:collapse;width:100%;margin:.8rem 0}th,td{border:1px solid #c9d5d9;padding:.4rem .6rem;text-align:left}th{background:#eef4f6}"
             ".src,.note{color:#5a6b72;font-size:.85rem}")
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{e(spec.title)}</title><style>{style}</style></head><body>{''.join(body)}</body></html>").encode("utf-8")


# ------------------------------------------------------------------ xlsx

def build_xlsx(spec: ExportSpec) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()

    def sheet(name: str):
        base = re.sub(r"[\[\]:*?/\\]", " ", name).strip()[:28] or "內容"
        title, n = base, 2
        while title.lower() in used:
            title, n = f"{base[:25]}_{n}", n + 1
        used.add(title.lower())
        return wb.create_sheet(title)

    def clean(value: str) -> str:
        text = _control_free(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@") else text  # a cell that starts like a formula stays text

    head_fill = PatternFill("solid", fgColor="DCEBEF")
    overview = sheet("摘要")
    overview.append([clean(spec.title)])
    overview["A1"].font = Font(bold=True, size=14)
    if spec.subtitle:
        overview.append([clean(spec.subtitle)])
    overview.append([])
    for section in spec.sections:
        if section.heading:
            overview.append([clean(section.heading)])
            overview.cell(overview.max_row, 1).font = Font(bold=True)
        for text in [*section.paragraphs, *section.bullets]:
            overview.append([clean(text)])
            overview.cell(overview.max_row, 1).alignment = Alignment(wrap_text=True, vertical="top")
        for src in section.sources:
            overview.append([clean(f"來源：{src}")])
    overview.append([])
    overview.append([DISCLAIMER])
    overview.column_dimensions["A"].width = 110

    for index, section in enumerate(spec.sections, 1):
        if not (section.table and section.table.usable()):
            continue
        table = section.table.square()
        ws = sheet(section.heading or f"表格{index}")
        ws.append([clean(c) for c in table.columns])
        for cell in ws[1]:
            cell.font, cell.fill = Font(bold=True), head_fill
        for row in table.rows:
            ws.append([clean(c) for c in row])
        for col in range(len(table.columns)):
            longest = max([len(table.columns[col])] + [len(r[col]) for r in table.rows])
            ws.column_dimensions[ws.cell(1, col + 1).column_letter].width = min(60, max(10, longest * 1.6 + 2))
        ws.freeze_panes = "A2"
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ------------------------------------------------------------------ docx (written directly: it is a small zip of XML)

def _run(text: str, *, bold: bool = False, size: int | None = None, color: str | None = None, italic: bool = False) -> str:
    props = f'<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="{CJK_FONT}"/>'
    props += "<w:b/>" if bold else ""
    props += "<w:i/>" if italic else ""
    props += f'<w:color w:val="{color}"/>' if color else ""
    props += f'<w:sz w:val="{size}"/>' if size else ""
    return f'<w:r><w:rPr>{props}</w:rPr><w:t xml:space="preserve">{xml_escape(_control_free(text))}</w:t></w:r>'


def _para(text: str, *, style: str | None = None, indent: int = 0, hanging: int = 0, **run) -> str:
    ppr = f'<w:pStyle w:val="{style}"/>' if style else ""
    ppr += f'<w:ind w:left="{indent}" w:hanging="{hanging}"/>' if indent else ""
    return f"<w:p><w:pPr>{ppr}<w:spacing w:after=\"80\"/></w:pPr>{_run(text, **run)}</w:p>"


def _table_xml(columns: list[str], rows: list[list[str]]) -> str:
    border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="B7C7CC"/>' for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    def cell(text: str, head: bool) -> str:
        shade = '<w:shd w:val="clear" w:color="auto" w:fill="DCEBEF"/>' if head else ""
        return f"<w:tc><w:tcPr>{shade}</w:tcPr>{_para(text, bold=head, size=20)}</w:tc>"
    xml = f'<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>{border}</w:tblBorders></w:tblPr>'
    xml += "<w:tr>" + "".join(cell(c, True) for c in columns) + "</w:tr>"
    xml += "".join("<w:tr>" + "".join(cell(c, False) for c in row) + "</w:tr>" for row in rows)
    return xml + "</w:tbl>" + _para("")


def build_docx(spec: ExportSpec) -> bytes:
    body = [_para(spec.title, style="Title")]
    if spec.subtitle:
        body.append(_para(spec.subtitle, color="5A6B72", italic=True))
    for section in spec.sections:
        if section.heading:
            body.append(_para(section.heading, style="Heading1"))
        body += [_para(p) for p in section.paragraphs]
        body += [_para(f"•\t{b}", indent=480, hanging=280) for b in section.bullets]
        if section.table and section.table.usable():
            t = section.table.square()
            body.append(_table_xml(t.columns, t.rows))
        if section.sources:
            body.append(_para("來源", bold=True, size=20, color="5A6B72"))
            body += [_para(f"•\t{s}", indent=480, hanging=280, size=20, color="5A6B72") for s in section.sources]
    body.append(_para(DISCLAIMER, size=18, color="5A6B72", italic=True))
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}><w:body>{"".join(body)}'
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr></w:body></w:document>')
    styles = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {ns}>'
              f'<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="{CJK_FONT}"/><w:sz w:val="22"/><w:lang w:val="en-US" w:eastAsia="zh-TW"/></w:rPr></w:rPrDefault></w:docDefaults>'
              '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
              '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="160"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/><w:color w:val="12343B"/></w:rPr></w:style>'
              '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="320" w:after="100"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/><w:color w:val="12343B"/></w:rPr></w:style>'
              '</w:styles>')
    content_types = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                     '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                     '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                     '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
    return out.getvalue()


# ------------------------------------------------------------------ pptx

def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)] or [[]]


def build_pptx(spec: ExportSpec) -> bytes:
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.util import Inches, Pt

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    ink, accent, muted = RGBColor(0x12, 0x34, 0x3B), RGBColor(0x1F, 0x8A, 0x8A), RGBColor(0x5A, 0x6B, 0x72)

    def text(slide, left, top, width, height, value, size, *, bold=False, color=ink, bullets=False):
        box = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height))
        frame = box.text_frame
        frame.word_wrap = True
        lines = value if isinstance(value, list) else [value]
        for i, line in enumerate(lines):
            p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
            run = p.add_run()
            run.text = _control_free(("• " if bullets else "") + line)
            run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(size), bold, color, CJK_FONT
            p.space_after = Pt(8)
        return box

    def footer(slide, number: int, sources: list[str] | None = None):
        if sources:
            text(slide, 0.6, 6.45, 12.1, 0.5, "來源：" + "；".join(sources)[:300], 10, color=muted)
        text(slide, 0.6, 6.95, 10.5, 0.4, DISCLAIMER, 9, color=muted)
        text(slide, 12.0, 6.95, 0.8, 0.4, str(number), 9, color=muted)

    def slide_title(slide, heading: str):
        bar = slide.shapes.add_shape(1, 0, 0, Inches(0.18), prs.slide_height)
        bar.fill.solid(); bar.fill.fore_color.rgb = accent; bar.line.fill.background()
        text(slide, 0.6, 0.4, 12.1, 0.9, heading, 28, bold=True)

    cover = prs.slides.add_slide(blank)
    band = cover.shapes.add_shape(1, 0, Inches(2.4), prs.slide_width, Inches(0.08))
    band.fill.solid(); band.fill.fore_color.rgb = accent; band.line.fill.background()
    text(cover, 0.9, 2.7, 11.5, 1.6, spec.title, 38, bold=True)
    if spec.subtitle:
        text(cover, 0.9, 4.5, 11.5, 1.0, spec.subtitle, 18, color=muted)
    text(cover, 0.9, 6.95, 11.5, 0.4, DISCLAIMER, 9, color=muted)
    number = 1

    for section in spec.sections:
        heading = section.heading or spec.title
        points = [*section.paragraphs, *section.bullets]
        pages = _chunks(points, BULLETS_PER_SLIDE) if points else []
        for page_index, page in enumerate(pages):
            number += 1
            slide = prs.slides.add_slide(blank)
            slide_title(slide, heading + (f"（{page_index + 1}/{len(pages)}）" if len(pages) > 1 else ""))
            text(slide, 0.6, 1.5, 12.1, 4.8, page, 20, bullets=True)
            footer(slide, number, section.sources if page_index == len(pages) - 1 and not (section.table and section.table.usable()) else None)
        if section.table and section.table.usable():
            table = section.table.square()
            groups = _chunks(table.rows, ROWS_PER_SLIDE)
            for group_index, rows in enumerate(groups):
                number += 1
                slide = prs.slides.add_slide(blank)
                slide_title(slide, heading + (f"（{group_index + 1}/{len(groups)}）" if len(groups) > 1 else ""))
                shape = slide.shapes.add_table(len(rows) + 1, len(table.columns), Inches(0.6), Inches(1.5), Inches(12.1), Inches(0.5) * (len(rows) + 1))
                for c, name in enumerate(table.columns):
                    shape.table.cell(0, c).text = _control_free(name)
                for r, row in enumerate(rows, 1):
                    for c, value in enumerate(row):
                        shape.table.cell(r, c).text = _control_free(value)
                for r in range(len(rows) + 1):
                    for c in range(len(table.columns)):
                        for p in shape.table.cell(r, c).text_frame.paragraphs:
                            for run in p.runs:
                                run.font.size, run.font.name, run.font.bold = Pt(12), CJK_FONT, r == 0
                footer(slide, number, section.sources if group_index == len(groups) - 1 else None)
        if not pages and not (section.table and section.table.usable()):
            number += 1
            slide = prs.slides.add_slide(blank)
            slide_title(slide, heading)
            footer(slide, number, section.sources)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


BUILDERS = {"pptx": build_pptx, "docx": build_docx, "xlsx": build_xlsx, "md": build_markdown, "csv": build_csv, "html": build_html}


def build(spec: ExportSpec) -> tuple[bytes, str, str]:
    """Returns (file bytes, media type, file name)."""
    return BUILDERS[spec.format](spec), MEDIA_TYPES[spec.format], safe_filename(spec.title, spec.format)
