"""Plain text out of a legacy file, and the chunking Qdrant gets."""
from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

MAX_CHARS = 400_000
CHUNK_CHARS = 700
SUPPORTED = {".pdf", ".docx", ".xlsx", ".pptx", ".txt"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "big5", "cp950", "utf-16"):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _clean(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\x00", "")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(line.rstrip() for line in text.split("\n"))).strip()


def extract_text(path: Path) -> str:
    """Deterministic text extraction (no OCR, no model). Empty string when the file holds no extractable text."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError(f"unsupported format {suffix}")
    if suffix == ".txt":
        return _clean(_decode(path.read_bytes())[:MAX_CHARS])
    from src.converter import FileConverter

    class DeterministicConverter(FileConverter):
        def _build_default_llm_client(self, llm_model=None):
            return None

    with tempfile.TemporaryDirectory() as tmp:
        result = DeterministicConverter().convert_file(str(path), str(Path(tmp) / "out.md"))
    if result.get("status") != "success":
        raise ValueError("document parser rejected the file")
    return _clean((result.get("content") or "")[:MAX_CHARS])


def chunk(text: str, size: int = CHUNK_CHARS) -> list[str]:
    """Paragraph-aware chunks of about `size` characters; an over-long paragraph is cut at the limit."""
    chunks: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        while len(paragraph) > size:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(paragraph[:size])
            paragraph = paragraph[size:]
        if not paragraph:
            continue
        if current and len(current) + len(paragraph) + 2 > size:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks
