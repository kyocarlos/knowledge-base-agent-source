import base64
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage

from src import chunk_assets
from src.converter import FileConverter
from src.chunker import chunk_document
from src.image_refs import merge_image_refs


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_excel_enrichment_exports_embedded_image_reference(tmp_path: Path, monkeypatch):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Summary"
    worksheet["A1"] = "throughput"
    worksheet.add_image(ExcelImage(BytesIO(ONE_PIXEL_PNG)), "B2")
    source = tmp_path / "report.xlsx"
    workbook.save(source)

    monkeypatch.setattr(chunk_assets, "ASSETS_ROOT", tmp_path / "assets")
    converter = FileConverter.__new__(FileConverter)
    converter._summarize_image_asset = lambda image, image_bytes=None: ""

    enrichment = converter._build_excel_enrichment(source)

    assert len(enrichment["image_refs"]) == 1
    asset = tmp_path / "assets" / enrichment["image_refs"][0]
    assert asset.is_file()
    assert "原圖引用：" + enrichment["image_refs"][0] in enrichment["text"]


def test_image_refs_are_merged_from_legacy_payload_shapes():
    assert merge_image_refs(
        ["asset://report/excel/image-01.png"],
        ["report/excel/image-02.png"],
        ["report/excel/image-01.png"],
    ) == ["report/excel/image-01.png", "report/excel/image-02.png"]


def test_chunker_preserves_image_refs_from_source_metadata(tmp_path: Path):
    converted = tmp_path / "task" / "converted"
    original = tmp_path / "task" / "original"
    converted.mkdir(parents=True)
    original.mkdir()
    markdown = converted / "report.md"
    markdown.write_text("# Report\n\n" + ("throughput result " * 40), encoding="utf-8")
    (original / "report.source.json").write_text(
        '{"image_refs": ["report/excel/image-01.png"]}', encoding="utf-8"
    )

    chunks = chunk_document(str(markdown))

    assert chunks
    assert any(
        "report/excel/image-01.png" in chunk["metadata"].get("image_refs", [])
        for chunk in chunks
    )
