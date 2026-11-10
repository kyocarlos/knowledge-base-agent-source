"""Document-library files of type .pptx and .md are read (they used to fail as UNSUPPORTED_DOCUMENT_FORMAT); other types keep their v1 behaviour."""
import hashlib
import zipfile
from dataclasses import replace

import pytest

from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.doclib_pipeline import DocLibPipeline
from src.csit_integration_v1.errors import IntegrationError


def pptx_bytes(tmp_path, slides):
    path = tmp_path / "make.pptx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
        for i, runs in enumerate(slides, 1):
            z.writestr(f"ppt/slides/slide{i}.xml", "<p:sld>" + "".join(f"<a:t>{r}</a:t>" for r in runs) + "</p:sld>")
    return path.read_bytes()


class Repo:
    def __init__(self):
        self.result = None

    def phase(self, job, name):
        pass

    def set_hash(self, job, digest):
        pass

    def checkpoint(self, job, name, info):
        pass

    def finish(self, job, result, refs):
        self.result = result


class Client:
    def __init__(self, content):
        self.content = content

    def download_file(self, job, destination):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.content)
        return hashlib.sha256(self.content).hexdigest()


class Writer:
    def __init__(self):
        self.text = None

    def write(self, text, job, semantic=None):
        self.text = text
        return {"collection": "c", "pointCount": 1, "indexId": "c/x"}


def run(tmp_path, name, content):
    repo, writer = Repo(), Writer()
    job = {"csit_job_id": "j1", "document_file_id": "f1", "original_file_name": name, "lease_token": "t", "content_type": "application/octet-stream",
           "expected_sha256": hashlib.sha256(content).hexdigest(), "file_size_bytes": len(content), "request_payload": {}}
    DocLibPipeline(replace(Settings(), storage_root=str(tmp_path)), repo, Client(content), writer).run(job)
    return repo.result, writer.text


def test_a_pptx_is_read_slide_by_slide(tmp_path):
    result, text = run(tmp_path, "Keysight_Tech_Day.pptx", pptx_bytes(tmp_path, [["5G NR 測試", "Handover"], ["Wi-Fi 7 MLO"]]))
    assert "5G NR 測試" in text and text.index("Handover") < text.index("Wi-Fi 7 MLO")
    assert result["extraction"]["sourceFormat"] == "pptx" and result["indexing"]["status"] == "Completed" and result["metadataSchemaVersion"] == "1.0"


def test_a_markdown_file_is_read(tmp_path):
    result, text = run(tmp_path, "notes.md", "# 實驗室規則\n借用儀器要先預約。".encode())
    assert "借用儀器要先預約" in text and result["extraction"]["sourceFormat"] == "md"


def test_a_broken_pptx_fails_with_its_own_code_not_as_unsupported(tmp_path):
    with pytest.raises(IntegrationError) as bad:
        run(tmp_path, "broken.pptx", b"this is not a zip package")
    assert bad.value.code in ("CORRUPT_DOCUMENT", "CORRUPT_FILE")
    with pytest.raises(IntegrationError) as locked:                      # an encrypted Office file is an OLE container
        run(tmp_path, "locked.pptx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"0" * 64)
    assert locked.value.code == "ENCRYPTED_DOCUMENT"


def test_images_and_unknown_types_still_fail_in_the_v1_vocabulary(tmp_path):
    for name in ("poster.png", "old.ppt", "data.zip"):
        with pytest.raises(IntegrationError) as bad:
            run(tmp_path, name, b"x" * 64)
        assert bad.value.code == "UNSUPPORTED_DOCUMENT_FORMAT", name


def test_a_replacement_version_of_a_test_report_fails_clearly_and_leaves_the_old_version_alone(tmp_path):
    from src.csit_integration_v1.v2_pipeline import V2Pipeline
    touched = []

    class Repo2:
        def __getattr__(self, name):
            touched.append(name)
            raise AssertionError("nothing may be done for it: " + name)

    class Qdrant:
        def __getattr__(self, name):
            touched.append(name)
            raise AssertionError(name)

    job = {"source_type": "TestReport", "original_file_name": "SIT-TR-WL-Throughput-X-V2.xlsx", "file_size_bytes": 10}
    with pytest.raises(IntegrationError) as e:
        V2Pipeline(replace(Settings(), storage_root=str(tmp_path)), Repo2(), None, Qdrant()).run(job)
    assert e.value.code == "REPLACEMENT_NOT_SUPPORTED" and e.value.retryable is False and not touched
