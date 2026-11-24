"""OCR for the pages of a PDF whose content is in pictures.

The converter reads the text layer of every page. A page exported from a slide deck or a scan often carries its real content as a picture (a feature list, a
frequency range, a table of results): the text layer then holds only a title, or nothing, and everything in the picture could not be asked about. Equipment
MT8821C, "Askey_SIT_ MT8821C 修改檔 V1.pdf": page 4 had 68 characters in its text layer and 625 once read, among them "Frequency Range: 30 MHz to 3.8 GHz / 3.8 GHz to
6.0 GHz (Option)".

Only pages with little text (and a picture, or no text at all) are read, with the Tesseract the worker already has (traditional Chinese + English). What OCR adds is
appended to that page under a label saying so; the text layer is never replaced or dropped. Lines the text layer already has, and lines that are mostly noise, are
left out. A page where OCR adds next to nothing stays as it was. Limits: pages per document and seconds per document; what is not reached stays as it was.

Off unless KM_CSIT_PDF_OCR=1: reading a document is not changed by deploying this code.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .image_reader import ImageReader, significant

SECTION = re.compile(r"^## PDF 頁面 (\d+)[ \t]*$", re.M)
TEXT_LABEL = "- 頁面文字："
PLACEHOLDER = "（本頁未抽取到可用文字，請參考原圖）"
OCR_LABEL = "（以下是圖片中的文字，由 OCR 辨識，可能有錯字或數字誤讀）"


def enabled() -> bool:
    return os.getenv("KM_CSIT_PDF_OCR", "").strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _norm(text: str) -> str:
    return re.sub(r"\W+", "", text or "").casefold()


def _keep(line: str) -> bool:
    line = line.strip()
    # OCR of a diagram or a photo gives scraps such as "f SR OM om": mostly letters, but no word of three characters
    return len(line) >= 3 and significant(line) >= 3 and significant(line) / len(line) >= 0.6 and any(significant(t) >= 3 for t in line.split())


def _render(pdf: Path, page: int, out_dir: Path, dpi: int, timeout: float = 60.0) -> Path | None:
    prefix = out_dir / f"page-{page:03d}"
    try:
        subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile", str(pdf), str(prefix)],
                       capture_output=True, timeout=timeout, check=True, shell=False)
    except (subprocess.SubprocessError, OSError):
        return None
    png = prefix.with_suffix(".png")
    return png if png.exists() else None


def enrich(text: str, pdf: Path, reader: ImageReader | None = None, *, max_pages: int | None = None, budget_seconds: float | None = None,
           sparse_chars: int | None = None, min_gain: int | None = None, dpi: int | None = None, workdir: Path | None = None) -> tuple[str, dict]:
    """-> (the converter's text with the OCR'd lines added to the pages that needed them, what was done)."""
    max_pages = max_pages if max_pages is not None else _int("KM_CSIT_PDF_OCR_MAX_PAGES", 40)
    budget = budget_seconds if budget_seconds is not None else float(_int("KM_CSIT_PDF_OCR_SECONDS", 100))
    sparse = sparse_chars if sparse_chars is not None else _int("KM_CSIT_PDF_OCR_SPARSE_CHARS", 150)
    gain_min = min_gain if min_gain is not None else _int("KM_CSIT_PDF_OCR_MIN_GAIN", 40)
    dpi = dpi if dpi is not None else _int("KM_CSIT_PDF_OCR_DPI", 200)
    reader = reader or ImageReader(vision=None)
    stats = {"candidates": 0, "ocr_pages": 0, "pages_enriched": [], "chars_added": 0, "failed": 0, "not_reached": 0, "seconds": 0.0, "available": bool(reader.tesseract)}
    if not reader.tesseract:
        return text, stats
    marks = list(SECTION.finditer(text))
    if not marks:
        return text, stats
    started = time.monotonic()
    tmp = Path(tempfile.mkdtemp(prefix="pdf-ocr-", dir=str(workdir) if workdir else None))
    pieces, cursor = [], 0
    try:
        for i, m in enumerate(marks):
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            section = text[m.start():end]
            page = int(m.group(1))
            pieces.append(text[cursor:m.start()])
            cursor = end
            head, sep, body = section.partition(TEXT_LABEL)
            body_stripped = body.strip()
            placeholder = body_stripped == PLACEHOLDER
            have = 0 if placeholder else len(re.sub(r"\s+", "", body))
            if not sep or have >= sparse or not (placeholder or "內嵌圖片" in head):
                pieces.append(section)
                continue
            stats["candidates"] += 1
            if stats["ocr_pages"] >= max_pages or time.monotonic() - started > budget:
                stats["not_reached"] += 1
                pieces.append(section)
                continue
            png = _render(pdf, page, tmp, dpi)
            ocr, problem = (reader._ocr(png) if png else (None, "page could not be rendered"))
            stats["ocr_pages"] += 1
            if png:
                try:
                    png.unlink()
                except OSError:
                    pass
            if problem or ocr is None:
                stats["failed"] += 1
                pieces.append(section)
                continue
            existing = _norm(body)
            fresh, seen = [], set()
            for raw_line in ocr.splitlines():
                # Columns of a slide or a table come out on one line with a wide gap. Each cell is judged on its own, but the cells that stay are kept on ONE line, joined by " | ":
                # a table row keeps its columns side by side ("Frequency Range | 30 MHz to 6.0 GHz | 30 MHz to 2.7 GHz"), so a value is not taken for the other column's.
                cells = [c for c in re.split(r"[ \t]{3,}", raw_line.strip()) if _keep(c)]
                line = " | ".join(c.strip() for c in cells)
                n = _norm(line)
                if n and n not in existing and n not in seen:
                    fresh.append(line)
                    seen.add(n)
            added = "\n".join(fresh)
            gain = len(re.sub(r"\s+", "", added))
            if gain < gain_min:
                pieces.append(section)
                continue
            stats["pages_enriched"].append(page)
            stats["chars_added"] += gain
            block = OCR_LABEL + "\n" + added
            if placeholder:
                section = head + sep + "\n" + block + "\n"
            else:
                section = section.rstrip("\n") + "\n\n" + block + "\n"
            pieces.append(section)
        pieces.append(text[cursor:])
    finally:
        stats["seconds"] = round(time.monotonic() - started, 1)
        shutil.rmtree(tmp, ignore_errors=True)
    return "".join(pieces), stats


def warning_for(stats: dict) -> str | None:
    pages = stats.get("pages_enriched") or []
    if not pages:
        return None
    shown = ", ".join(str(p) for p in pages[:20]) + (" ..." if len(pages) > 20 else "")
    extra = (f"; {stats['not_reached']} more image-based page(s) were not read (limit reached)" if stats.get("not_reached") else "")
    return f"text read by OCR from {len(pages)} image-based page(s) ({shown}); it can contain misread characters or numbers{extra}"


def apply(parsed, pdf_path, workdir, reader: ImageReader | None = None):
    """-> (the parsed extraction with the OCR'd text added, warning or None, whether OCR contributed). The parsed value is returned as it is when OCR is off or adds nothing."""
    if not enabled():
        return parsed, None, False
    try:
        new_text, stats = enrich(parsed.text, Path(pdf_path), reader, workdir=Path(workdir) if workdir else None)
    except Exception:  # noqa: BLE001 - reading a document never fails because the optional OCR step did
        return parsed, None, False
    if not stats["pages_enriched"]:
        return parsed, None, False
    return parsed.model_copy(update={"text": new_text}), warning_for(stats), True
