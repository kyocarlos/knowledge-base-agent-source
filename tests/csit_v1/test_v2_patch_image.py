"""Spec v1.4: .patch/.diff are read as plain text (never applied), images are read by OCR first and by a vision model only when OCR finds no text.
A file that yields nothing is never Completed."""
import hashlib
import io
import shutil
from dataclasses import replace

import pytest
from PIL import Image, ImageDraw, ImageFont

from src.csit_integration_v1 import image_reader
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.doclib_pipeline import DocLibPipeline
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.image_reader import ImageReader, Reading
from src.csit_integration_v1.v2_pipeline import V2Pipeline

PATCH = """From 1111111 Mon Sep 17 00:00:00 2001
Subject: [PATCH] fix wifi tx power

diff --git a/drivers/net/wifi/tx.c b/drivers/net/wifi/tx.c
index 111..222 100644
--- a/drivers/net/wifi/tx.c
+++ b/drivers/net/wifi/tx.c
@@ -10,3 +10,4 @@ int tx_power(void)
 	int p = 20;
-	return p;
+	system("touch /tmp/must-not-run");
+	return p + 1;
 }
@@ -40,2 +41,2 @@ int other(void)
-	return 0;
+	return 1;
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""


class Repo:
    def __init__(self):
        self.result = None
        self.phases = []

    def phase_job(self, job, name):
        self.phases.append(name)

    def phase(self, job, name):
        self.phases.append(name)

    def set_hash_job(self, job, digest):
        pass

    def set_hash(self, job, digest):
        pass

    def checkpoint_job(self, job, name, info):
        pass

    def checkpoint(self, job, name, info):
        pass

    def overrides_job(self, job):
        return {}

    def finish_job(self, job, result, refs):
        self.result = result

    def finish(self, job, result, refs):
        self.result = result


class Client:
    def __init__(self, content):
        self.content = content

    def _put(self, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.content)
        return hashlib.sha256(self.content).hexdigest()

    download_v2 = lambda self, job, destination: self._put(destination)  # noqa: E731
    download_file = lambda self, job, destination: self._put(destination)  # noqa: E731


class Writer:
    def __init__(self):
        self.text = None
        self.writes = 0

    def write(self, text, job, *args):
        self.text = text
        self.writes += 1
        return {"collection": "c", "pointCount": 1, "indexId": "c/x"}


class ImageDouble(ImageReader):
    """OCR and vision answers are scripted; the image gate, normalisation and the decision logic are the real ones."""
    def __init__(self, ocr_text, vision=None, **kw):
        super().__init__(vision=vision, tesseract="/bin/true", **kw)
        self._ocr_text = ocr_text

    def _ocr(self, png):
        return self._ocr_text, None


def png(text="", size=(400, 120)):
    im = Image.new("RGB", size, "white")
    if text:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 30)
        except OSError:
            font = ImageFont.load_default()
        d = ImageDraw.Draw(im)
        for i, line in enumerate(text.split("\n")):
            d.text((10, 10 + 40 * i), line, fill="black", font=font)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def job_for(name, content, source_type="VendorFile"):
    return {"event_id": "e1", "csit_job_id": "j1", "document_file_id": "f1", "document_id": "d1", "version": 1, "source_type": source_type,
            "original_file_name": name, "lease_token": "t", "content_type": "application/octet-stream",
            "expected_sha256": hashlib.sha256(content).hexdigest(), "file_size_bytes": len(content), "request_payload": {}}


def run_v2(tmp_path, name, content, images=None):
    repo, writer = Repo(), Writer()
    V2Pipeline(replace(Settings(), storage_root=str(tmp_path)), repo, Client(content), writer, images=images).run(job_for(name, content))
    return repo.result, writer.text, writer


# ---- .patch -------------------------------------------------------------------------------------------------------------------------

def test_a_patch_is_read_as_text_keeps_the_diff_and_names_the_file_of_every_hunk(tmp_path):
    result, text, _ = run_v2(tmp_path, "wifi-tx.patch", PATCH.encode())
    assert result["indexing"]["status"] == "Completed" and result["extraction"]["sourceFormat"] == "patch"
    assert result["extraction"]["method"] == "Text" and result["extraction"]["ocrUsed"] is False
    assert "+\tsystem(\"touch /tmp/must-not-run\");" in text            # the diff is kept as written
    assert "[file: drivers/net/wifi/tx.c]\n@@ -10,3 +10,4 @@" in text    # a chunk from the middle still names its file
    assert "[file: drivers/net/wifi/tx.c]\n@@ -40,2 +41,2 @@" in text
    assert "[file: README.md]\n@@ -1 +1 @@" in text
    assert not (tmp_path / "must-not-run").exists()


def test_a_patch_through_the_document_library_route_is_read_too(tmp_path):
    repo, writer = Repo(), Writer()
    content = PATCH.encode()
    DocLibPipeline(replace(Settings(), storage_root=str(tmp_path)), repo, Client(content), writer).run(job_for("a.patch", content))
    assert repo.result["indexing"]["status"] == "Completed" and "[file: README.md]" in writer.text


def test_a_diff_extension_is_read_like_a_patch(tmp_path):
    result, text, _ = run_v2(tmp_path, "change.diff", PATCH.encode())
    assert result["extraction"]["sourceFormat"] == "diff" and "[file: README.md]" in text


def test_patch_file_counts_are_extracted():
    from pathlib import Path
    import tempfile
    from src.csit_integration_v1.v2_pipeline import parse_patch
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "x.patch"
        p.write_text(PATCH, encoding="utf-8")
        table = parse_patch(p, Settings()).tables[0]
    assert table["rows"] == [["drivers/net/wifi/tx.c", 3, 2, 2], ["README.md", 1, 1, 1]]


@pytest.mark.parametrize("content,code", [(b"diff --git a/x b/x\n\x00\x01binary", "CORRUPT_FILE"), (b"\xff\xfe\xfa bad utf8 \x80", "CORRUPT_FILE"),
                                          (b"#!/bin/sh\nrm -rf /\n", "MALWARE_DETECTED"), (b"MZ\x90\x00", "MALWARE_DETECTED"), (b"", "CORRUPT_FILE")])
def test_a_patch_that_is_not_plain_text_is_rejected_and_nothing_is_indexed(tmp_path, content, code):
    writer = Writer()
    with pytest.raises(IntegrationError) as e:
        V2Pipeline(replace(Settings(), storage_root=str(tmp_path)), Repo(), Client(content), writer).run(job_for("bad.patch", content))
    assert e.value.code == code and writer.writes == 0


def test_an_empty_text_patch_is_not_completed(tmp_path):
    writer = Writer()
    with pytest.raises(IntegrationError) as e:
        V2Pipeline(replace(Settings(), storage_root=str(tmp_path)), Repo(), Client(b"  \n\n"), writer).run(job_for("blank.patch", b"  \n\n"))
    assert e.value.code == "EMPTY_EXTRACTION" and writer.writes == 0


# ---- images -------------------------------------------------------------------------------------------------------------------------

def test_without_ocr_or_vision_an_image_still_fails_as_unsupported(tmp_path):
    for images in (None, ImageReader(vision=None, tesseract=None)):
        with pytest.raises(IntegrationError) as e:
            run_v2(tmp_path, "shot.png", png("hello"), images=images)
        assert e.value.code == "UNSUPPORTED_FORMAT"


def test_a_screenshot_with_text_is_read_by_ocr_and_never_goes_to_the_vision_model(tmp_path):
    asked = []
    reader = ImageDouble("Error 0x80070057 invalid parameter\nDevice AP-7300 firmware 2.4.1", vision=lambda b: asked.append(1) or "x")
    result, text, _ = run_v2(tmp_path, "shot.png", png("x"), images=reader)
    assert result["extraction"]["method"] == "OCR" and result["extraction"]["ocrUsed"] is True and result["extraction"]["sourceFormat"] == "png"
    assert "AP-7300" in text and result["extraction"]["extractedCharacterCount"] == len(text) and not asked
    assert result["indexing"]["status"] == "Completed" and result["indexing"]["chunkCount"] == 1


def test_a_photo_without_text_is_described_by_vision_and_is_marked_as_a_description(tmp_path):
    reader = ImageDouble("", vision=lambda b: "A rack with three access points and cables.")
    result, text, _ = run_v2(tmp_path, "rack.png", png(), images=reader)
    assert result["extraction"]["method"] == "Visual" and result["extraction"]["ocrUsed"] is False
    assert text.startswith("[Visual description]") and "access points" in text
    assert any("vision model" in w for w in result["warnings"])


def test_ocr_text_and_a_description_together_are_mixed(tmp_path):
    reader = ImageDouble("ok 3", vision=lambda b: "A chart of throughput by channel width.")
    result, text, _ = run_v2(tmp_path, "chart.png", png(), images=reader)
    assert result["extraction"]["method"] == "Mixed" and result["extraction"]["ocrUsed"] is True and "ok 3" in text and "throughput" in text


def test_an_image_with_nothing_readable_is_failed_and_not_indexed(tmp_path):
    writer = Writer()
    with pytest.raises(IntegrationError) as e:
        V2Pipeline(replace(Settings(), storage_root=str(tmp_path)), Repo(), Client(png()), writer, images=ImageDouble("", vision=lambda b: "")).run(job_for("blank.png", png()))
    assert e.value.code == "EMPTY_EXTRACTION" and writer.writes == 0


def test_a_vision_outage_is_a_retryable_failure_not_an_empty_completion(tmp_path):
    def down(b):
        raise ConnectionError("gateway down")
    with pytest.raises(IntegrationError) as e:
        run_v2(tmp_path, "rack.png", png(), images=ImageDouble("", vision=down))
    assert e.value.code == "VISION_UNAVAILABLE" and e.value.retryable is True


def test_the_image_gate_checks_the_content_not_the_extension(tmp_path):
    with pytest.raises(IntegrationError) as e:
        run_v2(tmp_path, "fake.png", b"this is not an image at all", images=ImageDouble("x" * 50))
    assert e.value.code == "CORRUPT_FILE"
    jpeg = io.BytesIO()
    Image.new("RGB", (10, 10)).save(jpeg, "JPEG")
    with pytest.raises(IntegrationError) as e:   # a JPEG named .png
        run_v2(tmp_path, "fake.png", jpeg.getvalue(), images=ImageDouble("x" * 50))
    assert e.value.code == "MALWARE_DETECTED"


def test_an_oversized_image_is_refused_before_it_is_decoded_for_ocr(tmp_path, monkeypatch):
    monkeypatch.setattr(image_reader, "MAX_PIXELS", 100)
    with pytest.raises(IntegrationError) as e:
        run_v2(tmp_path, "big.png", png(size=(400, 400)), images=ImageDouble("x" * 50))
    assert e.value.code == "PARSER_LIMIT_EXCEEDED"


def test_the_working_images_are_removed_after_reading(tmp_path):
    run_v2(tmp_path, "shot.png", png(), images=ImageDouble("some readable text here for the index", vision=lambda b: "x"))
    left = [p.name for p in (tmp_path / "v2" / "e1").iterdir()]
    assert "ocr-input.png" not in left and "vision-input.png" not in left


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract is installed in the worker image only")
def test_real_tesseract_reads_a_text_screenshot(tmp_path):
    result, text, _ = run_v2(tmp_path, "shot.png", png("Error 0x80070057\nDevice AP-7300", size=(700, 140)), images=ImageReader(vision=None, langs="eng"))
    assert result["extraction"]["method"] == "OCR" and "AP-7300" in text.replace(" ", "")
