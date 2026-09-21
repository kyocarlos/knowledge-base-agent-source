from __future__ import annotations

import zipfile

import pytest

from src.converter.file_registry import resolve_parser


def test_binary_signature_mismatch_is_rejected(tmp_path):
    path = tmp_path / "report.xlsx"
    path.write_bytes(b"%PDF-1.7\nnot an excel file")
    with pytest.raises(ValueError, match="does not match"):
        resolve_parser(path)


def test_office_container_routes_to_structured_parser(tmp_path):
    path = tmp_path / "report.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    info = resolve_parser(path)
    assert info["parser_name"] == "word-structured-parser"
    assert info["parser_version"]


def test_standalone_image_is_allowlisted(tmp_path):
    path = tmp_path / "diagram.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 20)
    assert resolve_parser(path)["parser_name"] == "image-ocr-parser"

