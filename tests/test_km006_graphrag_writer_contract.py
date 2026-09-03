from src.graphrag import GraphRAGPipeline


class FakeGraph:
    def __init__(self):
        self.calls = []

    def query(self, query, params=None):
        self.calls.append((query, params or {}))
        return []


def test_graphrag_writer_uses_shared_relationship_contract():
    pipeline = object.__new__(GraphRAGPipeline)
    pipeline.graph = FakeGraph()
    assert pipeline.build_graph({
        "source_document": "DOC-003",
        "entities": [
            {"name": "Product-A", "type": "Product"},
            {"name": "Firmware-1", "type": "Firmware"},
        ],
        "relationships": [
            {"source": "Product-A", "target": "Firmware-1", "type": "HAS_FIRMWARE"}
        ],
    }) is True
    entity_query, entity_params = pipeline.graph.calls[0]
    relation_query, relation_params = pipeline.graph.calls[1]
    assert "entity_key" in entity_query
    assert "entity_key" in relation_query
    assert relation_params["relationships"][0]["source_document"] == "DOC-003"
    assert relation_params["relationships"][0]["source_chunk_id"] == "graphrag:unknown::chunk::0"
