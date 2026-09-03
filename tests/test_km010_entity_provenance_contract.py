from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_entity_writers_preserve_provenance_as_mentions_relations():
    ingest = (ROOT / "src" / "ingest.py").read_text(encoding="utf-8")
    graphrag = (ROOT / "src" / "graphrag" / "__init__.py").read_text(encoding="utf-8")

    for source in (ingest, graphrag):
        assert "MERGE (c:SourceChunk {id:" in source
        assert "MERGE (e)-[:MENTIONS" in source
        assert "ON CREATE SET e.description" in source
        assert "e.source_document" not in source
