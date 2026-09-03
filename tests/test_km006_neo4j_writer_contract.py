import json
from pathlib import Path
from unittest.mock import patch

from src.ingest import _write_neo4j_document


class FakeSession:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def run(self, query, **params):
        self.calls.append((query, params))


class FakeDriver:
    def __init__(self):
        self.session_value = FakeSession()

    def session(self):
        return self.session_value

    def close(self):
        pass


def test_neo4j_writer_uses_endpoint_identity_and_relationship_provenance(tmp_path: Path):
    document = tmp_path / "sample.md"
    document.write_text("sample", encoding="utf-8")
    metadata = {
        "source_system": "CSIT",
        "environment_id": "NPI",
        "project_id": "P1",
        "run_id": "RUN-1",
        "artifact_type": "report",
        "document_id": "DOC-1",
        "source_file_hash": "a" * 64,
        "document_version": "1.0.0",
    }
    (tmp_path / "sample.source.json").write_text(json.dumps(metadata), encoding="utf-8")
    driver = FakeDriver()
    result = {
        "entities": [
            {"name": "Product-A", "type": "Product", "namespace": "domain-a"},
            {"name": "Firmware-1", "type": "Firmware", "namespace": "domain-a"},
        ],
        "relationships": [
            {"source": "Product-A", "target": "Firmware-1", "type": "HAS_FIRMWARE"}
        ],
    }

    with patch("neo4j.GraphDatabase.driver", return_value=driver):
        _write_neo4j_document(
            "bolt://neo4j:7687", "neo4j", "unused", "sample", str(document), "sample", "4g5g", result=result
        )

    entity_calls = [call for call in driver.session_value.calls if "MERGE (e:Entity" in call[0]]
    relationship_calls = [call for call in driver.session_value.calls if "MERGE (s)-[r:RELATES_TO" in call[0]]
    assert len(entity_calls) == 2
    assert len(relationship_calls) == 1
    query, params = relationship_calls[0]
    assert "entity_key" in query
    assert "source_document" in query
    assert "source_chunk_id" in query
    assert params["evidence_type"] == "ai_inferred"
    assert params["review_status"] == "pending"


def test_cleanup_query_matches_km006_relationship_provenance():
    from src import ingest

    source = Path(ingest.__file__).read_text(encoding="utf-8")
    assert "r.source_document = $doc_name OR r.source = $doc_name" in source
