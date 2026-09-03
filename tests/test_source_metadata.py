import json

import pytest

from src.chunker import chunk_document
from src.source_metadata import SourceMetadataError, find_source_metadata_path, load_source_metadata


def test_loads_valid_sibling_metadata(tmp_path):
    document = tmp_path / "report.md"
    document.write_text("# Report\n\n" + "content " * 30, encoding="utf-8")
    sidecar = tmp_path / "report.source.json"
    sidecar.write_text(json.dumps({"document_id": "doc-1", "document_version": "2.0.0"}), encoding="utf-8")

    assert find_source_metadata_path(document) == sidecar
    assert load_source_metadata(document)["document_id"] == "doc-1"
    assert chunk_document(document)[0]["metadata"]["document_version"] == "2.0.0"


def test_loads_original_upload_sidecar_for_converted_document(tmp_path):
    converted = tmp_path / "processed" / "report.md"
    original = tmp_path / "original"
    converted.parent.mkdir()
    original.mkdir()
    converted.write_text("# Report\n\n" + "content " * 30, encoding="utf-8")
    sidecar = original / "report.source.json"
    sidecar.write_text(json.dumps({"document_id": "doc-original"}), encoding="utf-8")

    assert find_source_metadata_path(converted) == sidecar
    assert load_source_metadata(converted)["document_id"] == "doc-original"


@pytest.mark.parametrize("payload", ["{not-json", "[]", "null"])
def test_existing_malformed_sidecar_fails_closed(tmp_path, payload):
    document = tmp_path / "report.md"
    document.write_text("# Report\n\n" + "content " * 30, encoding="utf-8")
    (tmp_path / "report.source.json").write_text(payload, encoding="utf-8")

    with pytest.raises(SourceMetadataError):
        chunk_document(document)
