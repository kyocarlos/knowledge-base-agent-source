from __future__ import annotations

import zipfile

from src.converter import FileConverter


def _converter() -> FileConverter:
    converter = FileConverter.__new__(FileConverter)
    return converter


def test_docx_enrichment_keeps_heading_and_table_structure(tmp_path):
    path = tmp_path / "guide.docx"
    document = """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Setup</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Key</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Value</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body>
    </w:document>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)
    result = _converter()._build_docx_enrichment(path)
    assert "# Setup" in result["text"]
    assert "| Key | Value |" in result["text"]


def test_pptx_enrichment_keeps_slide_locator(tmp_path):
    path = tmp_path / "deck.pptx"
    slide = """<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:cSld><p:spTree><a:t>Title</a:t><a:t>Body</a:t></p:spTree></p:cSld>
    </p:sld>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", slide)
    result = _converter()._build_pptx_enrichment(path)
    assert "## PPT Slide 1" in result["text"]
    assert "Title" in result["text"] and "Body" in result["text"]

