from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.document_pipeline import DocumentPipelineError, run_document_pipeline
from src.document_normalization import NormalizationCatalog
from src.knowledge_package import build_package_id
from src.chunker import chunk_document
from src.vector_store import qdrant_point_id


@pytest.fixture
def catalog() -> NormalizationCatalog:
    return NormalizationCatalog.from_dict(
        {
            "aliases": {"technology": {"5G NR": "NR"}},
            "master_data": {
                "device": [
                    {
                        "canonical_id": "device-scu2050",
                        "canonical_value": "SCU2050",
                        "aliases": ["SCU-2050"],
                        "ontology_category": "device",
                    }
                ]
            },
        }
    )


class FakeConverter:
    def convert_file(self, input_path: str, output_path: str) -> dict[str, str]:
        Path(output_path).write_text("# converted report\n\n5G NR SCU-2050", encoding="utf-8")
        return {"status": "success", "output": output_path}


def test_pipeline_reuses_converter_and_existing_ingest_with_provenance(tmp_path, catalog):
    source = tmp_path / "report.txt"
    source.write_text("raw report", encoding="utf-8")
    calls: list[tuple[str, dict[str, object]]] = []

    def fake_ingest(path: str, **kwargs):
        calls.append((path, kwargs))
        return {"status": "accepted"}

    result = run_document_pipeline(
        input_path=source,
        document_id="report-1",
        metadata={"document_version": "2.0.0", "source_system": "anritsu"},
        normalization_catalog=catalog,
        normalization_values={"technology": "5G NR", "device": "SCU-2050"},
        normalization_namespaces={"device": "device"},
        output_dir=tmp_path / "package",
        converter=FakeConverter(),
        ingest_fn=fake_ingest,
    )

    assert result.route_plan.route == "text"
    assert result.package_metadata["package_id"] == build_package_id("report-1", "2.0.0")
    assert result.normalized_values["device"].canonical_id == "device-scu2050"
    assert len(calls) == 1
    assert calls[0][1] == {
        "enable_vector": True,
        "extraction_mode": "report",
        "preserve_assets": True,
    }

    sidecar = json.loads(Path(result.source_metadata_path).read_text(encoding="utf-8"))
    assert sidecar["package_id"] == result.package_metadata["package_id"]
    assert sidecar["source_locator"]["document_id"] == "report-1"
    assert sidecar["normalization_provenance"]["technology"]["raw_value"] == "5G NR"


def test_unknown_normalization_fails_before_converter_or_ingest(tmp_path, catalog):
    source = tmp_path / "report.txt"
    source.write_text("raw report", encoding="utf-8")
    converter_called = False

    class UnexpectedConverter:
        def convert_file(self, *_args, **_kwargs):
            nonlocal converter_called
            converter_called = True
            raise AssertionError("converter must not run")

    with pytest.raises(DocumentPipelineError, match="NORMALIZATION_NOT_PUBLISHABLE"):
        run_document_pipeline(
            input_path=source,
            document_id="report-1",
            metadata={},
            normalization_catalog=catalog,
            normalization_values={"device": "unknown-device"},
            normalization_namespaces={"device": "device"},
            output_dir=tmp_path / "package",
            converter=UnexpectedConverter(),
            ingest_fn=lambda *_args, **_kwargs: pytest.fail("ingest must not run"),
        )

    assert converter_called is False
    assert not list((tmp_path / "package").glob("*.source.json"))


def test_converter_failure_is_explicit_and_does_not_ingest(tmp_path, catalog):
    source = tmp_path / "report.txt"
    source.write_text("raw report", encoding="utf-8")

    class FailedConverter:
        def convert_file(self, *_args, **_kwargs):
            return {"status": "error", "error": "conversion failed"}

    with pytest.raises(DocumentPipelineError, match="CONVERSION_FAILED"):
        run_document_pipeline(
            input_path=source,
            document_id="report-1",
            metadata={},
            normalization_catalog=catalog,
            normalization_values={"technology": "5G NR"},
            output_dir=tmp_path / "package",
            converter=FailedConverter(),
            ingest_fn=lambda *_args, **_kwargs: pytest.fail("ingest must not run"),
        )


def test_existing_chunker_preserves_sidecar_lifecycle(tmp_path):
    markdown = tmp_path / "report.md"
    markdown.write_text("# WP10C\n\n" + ("published lifecycle evidence. " * 20), encoding="utf-8")
    sidecar = tmp_path / "report.source.json"
    sidecar.write_text(
        json.dumps(
            {
                "document_id": "report-1",
                "document_version": "1.0.0",
                "content_hash": "a" * 64,
                "publish_status": "published",
                "is_current": True,
            }
        ),
        encoding="utf-8",
    )

    chunks = chunk_document(markdown)

    assert chunks
    assert all(chunk["metadata"]["publish_status"] == "published" for chunk in chunks)
    assert all(chunk["metadata"]["is_current"] is True for chunk in chunks)
    assert all(chunk["metadata"]["content_hash"] == "a" * 64 for chunk in chunks)


def test_qdrant_point_identity_is_revision_scoped():
    v1 = "report-1@1.0.0::chunk::0::abc"
    v2 = "report-1@2.0.0::chunk::0::abc"
    assert qdrant_point_id(v1) == qdrant_point_id(v1)
    assert qdrant_point_id(v1) != qdrant_point_id(v2)
