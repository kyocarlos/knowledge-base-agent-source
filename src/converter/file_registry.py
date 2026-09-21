"""Fail-closed file type detection and parser registry."""
from __future__ import annotations

import mimetypes
import zipfile
from pathlib import Path


PARSER_VERSION = "phase1-registry-v1"
PARSER_REGISTRY = {
    ".pdf": "pdf-page-parser",
    ".xlsx": "excel-structured-parser",
    ".xls": "excel-structured-parser",
    ".docx": "word-structured-parser",
    ".doc": "word-markitdown-parser",
    ".pptx": "powerpoint-structured-parser",
    ".ppt": "powerpoint-markitdown-parser",
    ".png": "image-ocr-parser",
    ".jpg": "image-ocr-parser",
    ".jpeg": "image-ocr-parser",
    ".tif": "image-ocr-parser",
    ".tiff": "image-ocr-parser",
    ".webp": "image-ocr-parser",
    ".txt": "plain-text-parser",
    ".md": "markdown-parser",
    ".html": "html-parser",
    ".csv": "csv-parser",
    ".json": "json-parser",
    ".xml": "xml-parser",
    ".epub": "ebook-parser",
    ".msg": "outlook-message-parser",
}


def _zip_kind(path: Path) -> str | None:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return None
    if "word/document.xml" in names:
        return ".docx"
    if "ppt/presentation.xml" in names:
        return ".pptx"
    if "xl/workbook.xml" in names:
        return ".xlsx"
    return None


def detect_extension(path: str | Path) -> str | None:
    """Detect a conservative extension from magic bytes/container members."""
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    try:
        header = file_path.read_bytes()[:16]
    except OSError:
        return None
    if header.startswith(b"%PDF-"):
        return ".pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    if header.startswith(b"PK\x03\x04"):
        return _zip_kind(file_path)
    if suffix in PARSER_REGISTRY:
        return suffix
    return None


def resolve_parser(path: str | Path) -> dict[str, str]:
    file_path = Path(path)
    suffix = file_path.suffix.lower()
    if suffix not in PARSER_REGISTRY:
        raise ValueError(f"unsupported file extension: {suffix or '<none>'}")
    detected = detect_extension(file_path)
    # Text-like files have no reliable magic signature; known binary formats
    # must agree with their extension to prevent parser confusion.
    binary = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".docx", ".xlsx", ".pptx"}
    if detected in binary and detected != suffix:
        raise ValueError(f"file signature {detected} does not match extension {suffix}")
    return {"extension": suffix, "parser_name": PARSER_REGISTRY[suffix], "parser_version": PARSER_VERSION}

