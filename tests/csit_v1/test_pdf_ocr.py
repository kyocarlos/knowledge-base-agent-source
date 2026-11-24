"""OCR for PDF pages whose content is in pictures. Runs under pytest and on its own: python tests/csit_v1/test_pdf_ocr.py"""
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.csit_integration_v1 import pdf_ocr  # noqa: E402

TITLE_PAGE = ("## PDF 頁面 4\n- 頁面快照引用：asset://pdf/x/pages/page-004.png\n- 內嵌圖片：\n  - 圖片 1：asset://pdf/x/embedded/page-004/image-001.png\n- 頁面文字：\n"
              "One Box Tester for LTE-Advanced UE Development")
FULL_PAGE = "## PDF 頁面 5\n- 頁面快照引用：asset://pdf/x/pages/page-005.png\n- 內嵌圖片：\n  - 圖片 1：asset://pdf/x/embedded/page-005/image-001.png\n- 頁面文字：\n" + ("Radio frequency measurement text. " * 12)
BLANK_PAGE = "## PDF 頁面 6\n- 頁面快照引用：asset://pdf/x/pages/page-006.png\n- 頁面文字：\n（本頁未抽取到可用文字，請參考原圖）"
OCR_P4 = ("One Box Tester for LTE-Advanced UE Development\nThe new MT8821C is an one box tester designed for RF verification\n"
          "- Frequency Range: 30 MHz to 3.8 GHz\n3.8 GHz to 6.0 GHz (Option)\nf SR OM om\n~ , ;\n")


class FakeReader:
    def __init__(self, replies):
        self.tesseract, self.replies, self.calls = "/usr/bin/tesseract", list(replies), 0

    def _ocr(self, png):
        self.calls += 1
        r = self.replies.pop(0) if self.replies else ""
        return (r, None) if not isinstance(r, Exception) else (None, "OCR engine failed")


def _enrich(text, reader, **kw):
    real = pdf_ocr._render
    pdf_ocr._render = lambda pdf, page, out, dpi, timeout=60.0: Path(out) / f"page-{page:03d}.png"      # no page image needed for the logic tests
    try:
        return pdf_ocr.enrich(text, Path("x.pdf"), reader, **kw)
    finally:
        pdf_ocr._render = real


def test_a_page_with_a_title_and_a_picture_gets_what_ocr_read_and_nothing_twice():
    r = FakeReader([OCR_P4])
    out, st = _enrich(TITLE_PAGE, r)
    assert st["pages_enriched"] == [4] and r.calls == 1
    assert "Frequency Range: 30 MHz to 3.8 GHz" in out and "3.8 GHz to 6.0 GHz (Option)" in out and pdf_ocr.OCR_LABEL in out
    assert out.count("One Box Tester for LTE-Advanced UE Development") == 1          # the title the text layer already has is not repeated
    assert "f SR OM om" not in out and "~ , ;" not in out                              # noise lines are left out
    assert out.startswith(TITLE_PAGE)                                                  # the text layer is kept as it was


def test_columns_of_one_ocr_line_stay_on_one_line_so_a_table_row_keeps_its_columns():
    two = "+ Parallelphone measurement" + " " * 33 + "+ Frequency Range: 30 MHz to 3.8 GHz\n«Internal server" + " " * 90 + "3.8 GHz to 6.0 GHz (Option)\n"
    out, st = _enrich(TITLE_PAGE, FakeReader([two]))
    assert "+ Frequency Range: 30 MHz to 3.8 GHz" in out and "3.8 GHz to 6.0 GHz (Option)" in out and "+ Parallelphone measurement" in out
    assert "   " not in out.split(pdf_ocr.OCR_LABEL, 1)[1]
    table = "MT8821C vs MT8820C\nFrequency | 30 MHz to 6.0 GHz" + " " * 40 + "30 MHz to 2.7 GHz, 3.4 GHz to 3.8 GHz\nInterface | Main: RF In/Out (Max. 4 ports)" + " " * 30 + "Main: RF In/Out (Max. 2 ports)\n"
    out, st = _enrich(TITLE_PAGE, FakeReader([table]))
    assert "Frequency | 30 MHz to 6.0 GHz | 30 MHz to 2.7 GHz, 3.4 GHz to 3.8 GHz" in out, out        # the MT8820C cell stays on the MT8821C row, to the right
    assert "Interface | Main: RF In/Out (Max. 4 ports) | Main: RF In/Out (Max. 2 ports)" in out


def test_a_page_with_plenty_of_text_is_not_read():
    r = FakeReader([OCR_P4])
    out, st = _enrich(FULL_PAGE, r)
    assert out == FULL_PAGE and r.calls == 0 and st["candidates"] == 0


def test_the_placeholder_of_a_page_without_text_is_replaced_by_what_ocr_read():
    r = FakeReader(["報價單 QUOTATION\n報價單號: Q-20211012-002\n總計 EURO 12,345"])
    out, st = _enrich(BLANK_PAGE, r)
    assert st["pages_enriched"] == [6] and "本頁未抽取到可用文字" not in out and "Q-20211012-002" in out and "EURO 12,345" in out


def test_a_page_where_ocr_adds_next_to_nothing_stays_as_it_was():
    r = FakeReader(["One Box Tester for LTE-Advanced UE Development\n"])
    out, st = _enrich(TITLE_PAGE, r)
    assert out == TITLE_PAGE and st["pages_enriched"] == [] and st["ocr_pages"] == 1
    out, st = _enrich(BLANK_PAGE, FakeReader(["Anritsu\n"]))                        # a logo page adds nothing worth indexing; the placeholder stays
    assert out == BLANK_PAGE


def test_limits_leave_the_rest_of_the_document_as_it_was():
    text = "\n".join(TITLE_PAGE.replace("頁面 4", f"頁面 {n}") for n in range(1, 6))
    r = FakeReader([OCR_P4] * 5)
    out, st = _enrich(text, r, max_pages=2)
    assert st["ocr_pages"] == 2 and st["not_reached"] == 3 and st["pages_enriched"] == [1, 2]
    assert pdf_ocr.warning_for(st) and "not read" in pdf_ocr.warning_for(st)


def test_an_ocr_failure_on_a_page_never_loses_the_page():
    out, st = _enrich(TITLE_PAGE, FakeReader([RuntimeError()]))
    assert out == TITLE_PAGE and st["failed"] == 1


def test_without_an_ocr_engine_nothing_changes():
    r = FakeReader([OCR_P4])
    r.tesseract = None
    out, st = pdf_ocr.enrich(TITLE_PAGE, Path("x.pdf"), r)
    assert out == TITLE_PAGE and not st["available"]


def test_it_is_off_unless_switched_on():
    parsed = SimpleNamespace(text=TITLE_PAGE, model_copy=lambda update: SimpleNamespace(**{**{"text": TITLE_PAGE}, **update}))
    os.environ.pop("KM_CSIT_PDF_OCR", None)
    got, warning, used = pdf_ocr.apply(parsed, "x.pdf", None, FakeReader([OCR_P4]))
    assert got is parsed and warning is None and used is False


def test_real_ocr_reads_a_picture_only_pdf():
    if not (shutil.which("tesseract") and shutil.which("pdftoppm")):
        return
    from PIL import Image, ImageDraw, ImageFont
    work = Path(tempfile.mkdtemp())
    try:
        img = Image.new("RGB", (1240, 700), "white")
        font = ImageFont.load_default(size=44)
        d = ImageDraw.Draw(img)
        d.text((60, 80), "Frequency Range: 30 MHz to 3.8 GHz", fill="black", font=font)
        d.text((60, 180), "3.8 GHz to 6.0 GHz (Option)", fill="black", font=font)
        pdf = work / "slide.pdf"
        img.save(pdf, "PDF", resolution=150)
        out, st = pdf_ocr.enrich(BLANK_PAGE.replace("頁面 6", "頁面 1"), pdf, None, workdir=work)
        assert st["pages_enriched"] == [1], st
        assert "30 MHz to 3.8 GHz" in out and "6.0 GHz" in out, out
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    bad = 0
    for name, fn in sorted((k, v) for k, v in dict(globals()).items() if k.startswith("test_")):
        try:
            fn()
            print("PASS", name)
        except Exception:  # noqa: BLE001
            bad += 1
            print("FAIL", name)
            traceback.print_exc()
    print("OVERALL:", "ALL PASS" if not bad else f"{bad} FAILED")
    sys.exit(1 if bad else 0)
