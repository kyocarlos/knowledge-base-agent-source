"""BUG-003: a relationship must keep its two entity names; the document it came from is a separate fact."""
import json
from types import SimpleNamespace

from src.graphrag import GraphRAGPipeline


class FakeLLM:
    def __init__(self, payload):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])))


class FakeGraph:
    def __init__(self):
        self.calls = []

    def query(self, cypher, params=None):
        self.calls.append((cypher, params))


PAYLOAD = {"entities": [{"name": "A", "type": "t", "description": "d"}, {"name": "B", "type": "t", "description": "d"}],
           "relationships": [{"source": "A", "type": "uses", "target": "B", "description": "A uses B"}]}
CHUNKS = [{"content": "A uses B", "metadata": {"source": "doc-1.pdf"}}]


def _pipeline(graph=None):
    p = GraphRAGPipeline.__new__(GraphRAGPipeline)      # no Neo4j / LangChain needed
    p.graph = graph
    return p


def test_extracted_relationship_keeps_its_source_entity_and_records_the_document_separately():
    out = _pipeline().extract_entities(CHUNKS, FakeLLM(PAYLOAD), "m")
    rel = out["relationships"][0]
    assert rel["source"] == "A" and rel["target"] == "B"
    assert rel["doc_source"] == "doc-1.pdf"
    assert out["entities"][0]["source"] == "doc-1.pdf"      # entities still carry the document in "source"


def test_graph_write_matches_entities_by_name_and_stores_the_document_on_the_edge():
    g = FakeGraph()
    p = _pipeline(g)
    p._create_vector_index = lambda: None
    assert p.build_graph(p.extract_entities(CHUNKS, FakeLLM(PAYLOAD), "m")) is True
    cypher, params = g.calls[1]
    assert "{name: rel.source}" in cypher and "{name: rel.target}" in cypher
    assert "r.source = rel.doc_source" in cypher
    assert params["relationships"][0]["source"] == "A"
