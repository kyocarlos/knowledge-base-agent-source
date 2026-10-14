"""Fail-closed document detection and source-location contract for WP10A.

The module stops at a validated route plan. It does not invoke OCR or an LLM,
write files, mutate a database, or create a Knowledge Package record.
"""

from __future__ import annotations

import csv
import io
import posixpath
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Mapping


class DocumentIntelligenceError(ValueError):
    """Stable error that does not disclose filenames, paths, or content."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class DocumentType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    PDF = "pdf"
    OFFICE = "office"
    TABLE = "table"
    EXCEL = "excel"
    MIXED = "mixed"


class LocatorKind(str, Enum):
    DOCUMENT = "document"
    PDF_PAGE = "pdf_page"
    IMAGE_REGION = "image_region"
    OFFICE_PART = "office_part"
    EXCEL_CELL = "excel_cell"
    EXCEL_RANGE = "excel_range"


@dataclass(frozen=True, slots=True)
class SourceLocator:
    """Logical source position; local filesystem paths are never stored."""

    document_id: str
    kind: LocatorKind
    page: int | None = None
    region: str | None = None
    sheet: str | None = None
    cell: str | None = None
    cell_range: str | None = None
    part: str | None = None

    def __post_init__(self) -> None:
        logical_id = self.document_id.strip()
        if not logical_id or "/" in logical_id or "\\" in logical_id:
            raise DocumentIntelligenceError(
                "INVALID_DOCUMENT_ID", "document_id must be a logical identifier"
            )
        if self.page is not None and self.page < 1:
            raise DocumentIntelligenceError("INVALID_PAGE", "page must be positive")
        if self.kind == LocatorKind.PDF_PAGE and self.page is None:
            raise DocumentIntelligenceError("MISSING_PAGE", "pdf_page locator requires page")
        if self.kind in {LocatorKind.EXCEL_CELL, LocatorKind.EXCEL_RANGE} and not (
            self.sheet and self.sheet.strip()
        ):
            raise DocumentIntelligenceError("MISSING_SHEET", "Excel locator requires sheet")
        if self.kind == LocatorKind.EXCEL_CELL and not (self.cell and self.cell.strip()):
            raise DocumentIntelligenceError("MISSING_CELL", "excel_cell locator requires cell")
        if self.kind == LocatorKind.EXCEL_RANGE and not (
            self.cell_range and self.cell_range.strip()
        ):
            raise DocumentIntelligenceError("MISSING_RANGE", "excel_range locator requires range")

    def as_dict(self) -> dict[str, object]:
        return {
            key: value
            for key, value in {
                "document_id": self.document_id,
                "kind": self.kind.value,
                "page": self.page,
                "region": self.region,
                "sheet": self.sheet,
                "cell": self.cell,
                "range": self.cell_range,
                "part": self.part,
            }.items()
            if value is not None
        }


@dataclass(frozen=True, slots=True)
class DocumentRoutePlan:
    """Validated, deterministic output boundary for later routing."""

    document_id: str
    document_type: DocumentType
    primary_type: DocumentType
    route: str
    requires_ocr: bool
    source_locator: SourceLocator
    package_schema_version: str = "1.0"
    validation_required: bool = True
    database_mutation_performed: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "document_type": self.document_type.value,
            "primary_type": self.primary_type.value,
            "route": self.route,
            "requires_ocr": self.requires_ocr,
            "source_locator": self.source_locator.as_dict(),
            "package_schema_version": self.package_schema_version,
            "validation_required": self.validation_required,
            "database_mutation_performed": self.database_mutation_performed,
        }


@dataclass(frozen=True, slots=True)
class DetectionPolicy:
    """Configurable allowlist and bounded inspection policy."""

    extensions: Mapping[str, tuple[DocumentType, str]]
    max_inspection_bytes: int = 32 * 1024 * 1024
    max_office_members: int = 20_000

    def __post_init__(self) -> None:
        if self.max_inspection_bytes < 1 or self.max_office_members < 1:
            raise ValueError("inspection limits must be positive")


@dataclass(frozen=True, slots=True)
class _Signature:
    primary_type: DocumentType
    media_type: str
    has_embedded_media: bool = False


_DEFAULT_EXTENSIONS = {
    ".txt": (DocumentType.TEXT, "text/plain"),
    ".md": (DocumentType.TEXT, "text/markdown"),
    ".json": (DocumentType.TEXT, "application/json"),
    ".xml": (DocumentType.TEXT, "application/xml"),
    ".html": (DocumentType.TEXT, "text/html"),
    ".yaml": (DocumentType.TEXT, "application/yaml"),
    ".yml": (DocumentType.TEXT, "application/yaml"),
    ".log": (DocumentType.TEXT, "text/plain"),
    ".csv": (DocumentType.TABLE, "text/csv"),
    ".tsv": (DocumentType.TABLE, "text/tab-separated-values"),
    ".pdf": (DocumentType.PDF, "application/pdf"),
    ".docx": (
        DocumentType.OFFICE,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
    ".pptx": (
        DocumentType.OFFICE,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ),
    ".xlsx": (
        DocumentType.EXCEL,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".xlsm": (DocumentType.EXCEL, "application/vnd.ms-excel.sheet.macroenabled.12"),
    ".png": (DocumentType.IMAGE, "image/png"),
    ".jpg": (DocumentType.IMAGE, "image/jpeg"),
    ".jpeg": (DocumentType.IMAGE, "image/jpeg"),
    ".gif": (DocumentType.IMAGE, "image/gif"),
    ".webp": (DocumentType.IMAGE, "image/webp"),
}

DEFAULT_DETECTION_POLICY = DetectionPolicy(MappingProxyType(_DEFAULT_EXTENSIONS))


def _logical_name(filename: str) -> str:
    value = str(filename or "").replace("\\", "/")
    name = posixpath.basename(value).strip()
    if not name or name in {".", ".."}:
        raise DocumentIntelligenceError("MISSING_FILENAME", "filename is required")
    return name


def _extension(filename: str) -> str:
    return PurePosixPath(_logical_name(filename)).suffix.lower()


def _zip_signature(content: bytes, policy: DetectionPolicy) -> _Signature | None:
    if not content.startswith(b"PK\x03\x04"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            if len(members) > policy.max_office_members:
                raise DocumentIntelligenceError(
                    "CONTAINER_LIMIT_EXCEEDED", "Office container member limit exceeded"
                )
            names = tuple(member.filename.lower() for member in members)
    except DocumentIntelligenceError:
        raise
    except (OSError, zipfile.BadZipFile):
        raise DocumentIntelligenceError("INVALID_CONTAINER", "Office container is invalid") from None
    if "[content_types].xml" not in names:
        raise DocumentIntelligenceError(
            "UNKNOWN_CONTAINER", "ZIP container is not a supported Office document"
        )
    has_media = any("/media/" in f"/{name}" or name.startswith("media/") for name in names)
    if any(name.startswith("xl/") for name in names):
        macro = "xl/vbaproject.bin" in names
        media_type = (
            "application/vnd.ms-excel.sheet.macroenabled.12"
            if macro
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        return _Signature(DocumentType.EXCEL, media_type, has_media)
    if any(name.startswith("word/") for name in names):
        return _Signature(
            DocumentType.OFFICE,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            has_media,
        )
    if any(name.startswith("ppt/") for name in names):
        return _Signature(
            DocumentType.OFFICE,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            has_media,
        )
    raise DocumentIntelligenceError("UNKNOWN_OFFICE", "Office container type is not allowlisted")


def _image_signature(content: bytes) -> str | None:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _looks_like_table(content: bytes, extension: str) -> bool:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    delimiter = "\t" if extension == ".tsv" else None
    sample = text[:8192]
    try:
        dialect = csv.excel_tab if delimiter else csv.Sniffer().sniff(sample, delimiters=",;|")
        rows = list(csv.reader(io.StringIO(sample), dialect))
    except (csv.Error, UnicodeError):
        return False
    return len(rows) >= 2 and len(rows[0]) >= 2 and len(rows[0]) == len(rows[1])


def _text_signature(content: bytes) -> bool:
    if not content:
        return True
    if b"\x00" in content[:8192]:
        return False
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    sample = text[:8192]
    return sum(char.isprintable() or char in "\r\n\t" for char in sample) / max(1, len(sample)) >= 0.90


def _detected_signature(content: bytes, extension: str, policy: DetectionPolicy) -> _Signature:
    if content.startswith(b"%PDF-"):
        return _Signature(DocumentType.PDF, "application/pdf")
    image_mime = _image_signature(content)
    if image_mime:
        return _Signature(DocumentType.IMAGE, image_mime)
    container = _zip_signature(content, policy)
    if container:
        return container
    if extension in {".csv", ".tsv"} and _looks_like_table(content, extension):
        return _Signature(DocumentType.TABLE, policy.extensions[extension][1])
    if _text_signature(content):
        return _Signature(DocumentType.TEXT, policy.extensions.get(extension, (DocumentType.TEXT, "text/plain"))[1])
    raise DocumentIntelligenceError("UNSUPPORTED_CONTENT", "content signature is not allowlisted")


def _declared_mime_matches(supplied: str, expected: str) -> bool:
    value = supplied.lower().split(";", 1)[0].strip()
    return not value or value == "application/octet-stream" or value == expected.lower()


def _locator(document_id: str, primary: DocumentType) -> SourceLocator:
    if primary == DocumentType.PDF:
        return SourceLocator(document_id, LocatorKind.PDF_PAGE, page=1)
    if primary == DocumentType.IMAGE:
        return SourceLocator(document_id, LocatorKind.IMAGE_REGION, region="full")
    if primary == DocumentType.OFFICE:
        return SourceLocator(document_id, LocatorKind.OFFICE_PART, part="document")
    if primary == DocumentType.EXCEL:
        return SourceLocator(
            document_id,
            LocatorKind.EXCEL_RANGE,
            sheet="__UNRESOLVED__",
            cell_range="__UNRESOLVED__",
        )
    return SourceLocator(document_id, LocatorKind.DOCUMENT)


def detect_document(
    *,
    document_id: str,
    filename: str,
    content: bytes,
    mime_type: str | None = None,
    policy: DetectionPolicy = DEFAULT_DETECTION_POLICY,
) -> DocumentRoutePlan:
    """Classify bytes and return a deterministic, non-mutating route plan."""
    if not isinstance(content, (bytes, bytearray, memoryview)):
        raise DocumentIntelligenceError("INVALID_CONTENT", "content must be bytes")
    raw = bytes(content)
    if len(raw) > policy.max_inspection_bytes:
        raise DocumentIntelligenceError("CONTENT_LIMIT_EXCEEDED", "content inspection limit exceeded")
    extension = _extension(filename)
    expected = policy.extensions.get(extension)
    if expected is None:
        raise DocumentIntelligenceError("UNSUPPORTED_EXTENSION", "filename extension is not allowlisted")
    expected_type, expected_mime = expected
    signature = _detected_signature(raw, extension, policy)
    if signature.primary_type != expected_type or signature.media_type.lower() != expected_mime.lower():
        raise DocumentIntelligenceError(
            "EXTENSION_CONTENT_MISMATCH", "filename extension does not match content signature"
        )
    if mime_type and not _declared_mime_matches(mime_type, expected_mime):
        raise DocumentIntelligenceError(
            "MIME_CONTENT_MISMATCH", "declared MIME type does not match filename and content"
        )
    document_type = DocumentType.MIXED if signature.has_embedded_media else signature.primary_type
    return DocumentRoutePlan(
        document_id=document_id,
        document_type=document_type,
        primary_type=signature.primary_type,
        route=document_type.value,
        requires_ocr=signature.primary_type in {DocumentType.IMAGE, DocumentType.PDF}
        or signature.has_embedded_media,
        source_locator=_locator(document_id, signature.primary_type),
    )


def pdf_locator(document_id: str, *, page: int, region: str | None = None) -> SourceLocator:
    return SourceLocator(document_id, LocatorKind.PDF_PAGE, page=page, region=region)


def image_locator(document_id: str, *, region: str | None = None) -> SourceLocator:
    return SourceLocator(document_id, LocatorKind.IMAGE_REGION, region=region or "full")


def excel_cell_locator(document_id: str, *, sheet: str, cell: str) -> SourceLocator:
    return SourceLocator(document_id, LocatorKind.EXCEL_CELL, sheet=sheet, cell=cell)


def excel_range_locator(document_id: str, *, sheet: str, cell_range: str) -> SourceLocator:
    return SourceLocator(document_id, LocatorKind.EXCEL_RANGE, sheet=sheet, cell_range=cell_range)
