from __future__ import annotations

import io
import zipfile

import pytest

from src.document_intelligence import (
    DetectionPolicy,
    DocumentIntelligenceError,
    DocumentType,
    detect_document,
    excel_cell_locator,
    excel_range_locator,
    image_locator,
    pdf_locator,
)


def office_fixture(kind: str, *, media: bool = False, macro: bool = False) -> bytes:
    prefix = {
        "word": "word/document.xml",
        "ppt": "ppt/presentation.xml",
        "excel": "xl/workbook.xml",
    }[kind]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(prefix, "<document/>")
        if media:
            archive.writestr(f"{kind}/media/image1.png", b"\x89PNG\r\n\x1a\n")
        if macro:
            archive.writestr("xl/vbaProject.bin", b"macro fixture")
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "mime", "content", "expected"),
    [
        ("readme.txt", "text/plain", b"hello\nworld", DocumentType.TEXT),
        ("notes.md", "text/markdown", b"# Heading\n", DocumentType.TEXT),
        ("data.json", "application/json", b'{"value": 1}', DocumentType.TEXT),
        ("photo.png", "image/png", b"\x89PNG\r\n\x1a\n", DocumentType.IMAGE),
        ("capture.pdf", "application/pdf", b"%PDF-1.7\n", DocumentType.PDF),
        (
            "guide.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            office_fixture("word"),
            DocumentType.OFFICE,
        ),
        (
            "slides.pptx",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            office_fixture("ppt"),
            DocumentType.OFFICE,
        ),
        ("table.csv", "text/csv", b"name,value\na,1\n", DocumentType.TABLE),
        ("table.tsv", "text/tab-separated-values", b"name\tvalue\na\t1\n", DocumentType.TABLE),
        (
            "book.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            office_fixture("excel"),
            DocumentType.EXCEL,
        ),
        (
            "book.xlsm",
            "application/vnd.ms-excel.sheet.macroEnabled.12",
            office_fixture("excel", macro=True),
            DocumentType.EXCEL,
        ),
        (
            "mixed.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            office_fixture("word", media=True),
            DocumentType.MIXED,
        ),
    ],
)
def test_supported_types_route_without_database_mutation(filename, mime, content, expected):
    result = detect_document(
        document_id="doc-1", filename=filename, content=content, mime_type=mime
    )
    assert result.document_type is expected
    assert result.database_mutation_performed is False
    assert result.validation_required is True


def test_extension_and_mime_mismatch_fail_closed_without_leaking_path():
    with pytest.raises(DocumentIntelligenceError) as error:
        detect_document(
            document_id="doc-1",
            filename="/sensitive/location/wrong.txt",
            content=b"%PDF-1.7\n",
            mime_type="text/plain",
        )
    assert error.value.code == "EXTENSION_CONTENT_MISMATCH"
    assert "sensitive" not in str(error.value)
    assert "wrong.txt" not in str(error.value)

    with pytest.raises(DocumentIntelligenceError) as mime_error:
        detect_document(
            document_id="doc-1",
            filename="image.png",
            content=b"\x89PNG\r\n\x1a\n",
            mime_type="text/plain",
        )
    assert mime_error.value.code == "MIME_CONTENT_MISMATCH"

    with pytest.raises(DocumentIntelligenceError) as office_error:
        detect_document(
            document_id="doc-1",
            filename="wrong.docx",
            content=office_fixture("ppt"),
        )
    assert office_error.value.code == "EXTENSION_CONTENT_MISMATCH"


def test_macro_enabled_extension_requires_macro_container():
    with pytest.raises(DocumentIntelligenceError) as error:
        detect_document(
            document_id="doc-1",
            filename="renamed.xlsm",
            content=office_fixture("excel", macro=False),
        )
    assert error.value.code == "EXTENSION_CONTENT_MISMATCH"


def test_rerun_is_deterministic_and_unknown_extensions_fail_closed():
    first = detect_document(
        document_id="doc-1", filename="data.csv", content=b"a,b\n1,2\n", mime_type="text/csv"
    ).as_dict()
    second = detect_document(
        document_id="doc-1", filename="data.csv", content=b"a,b\n1,2\n", mime_type="text/csv"
    ).as_dict()
    assert first == second
    with pytest.raises(DocumentIntelligenceError) as error:
        detect_document(document_id="doc-1", filename="data.bin", content=b"a,b\n1,2\n")
    assert error.value.code == "UNSUPPORTED_EXTENSION"


def test_configurable_content_limit_fails_closed():
    from src.document_intelligence import DEFAULT_DETECTION_POLICY

    policy = DetectionPolicy(DEFAULT_DETECTION_POLICY.extensions, max_inspection_bytes=4)
    with pytest.raises(DocumentIntelligenceError) as error:
        detect_document(
            document_id="doc-1", filename="note.txt", content=b"12345", policy=policy
        )
    assert error.value.code == "CONTENT_LIMIT_EXCEEDED"


def test_source_locators_preserve_required_positions():
    assert pdf_locator("doc-1", page=3, region="x=10,y=20,w=30,h=40").as_dict() == {
        "document_id": "doc-1",
        "kind": "pdf_page",
        "page": 3,
        "region": "x=10,y=20,w=30,h=40",
    }
    assert image_locator("doc-1").as_dict()["region"] == "full"
    assert excel_cell_locator("doc-1", sheet="Summary", cell="B7").as_dict()["cell"] == "B7"
    assert excel_range_locator("doc-1", sheet="Summary", cell_range="A1:D9").as_dict()["range"] == "A1:D9"
