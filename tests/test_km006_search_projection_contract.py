from pathlib import Path


SEARCH_SOURCE = Path(__file__).parents[1].joinpath("src", "search", "__init__.py")


def test_deep_search_projects_relationship_provenance():
    source = SEARCH_SOURCE.read_text(encoding="utf-8")
    for field in ("source_document", "source_chunk_id", "evidence_type", "review_status"):
        assert f"{field}: r.{field}" in source


def test_graph_context_formats_relationship_provenance():
    source = SEARCH_SOURCE.read_text(encoding="utf-8")
    assert 'connection.get("source_document")' in source
    assert 'connection.get("source_chunk_id")' in source
