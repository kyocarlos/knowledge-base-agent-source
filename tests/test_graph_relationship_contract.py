import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).parents[1] / "src" / "graph_relationship_contract.py"
_SPEC = importlib.util.spec_from_file_location("graph_relationship_contract", _MODULE_PATH)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MODULE)
build_graph_contract = _MODULE.build_graph_contract


def test_same_display_name_isolated_by_namespace_and_relationship_keeps_provenance():
    result = build_graph_contract(
        [
            {"name": "Model-X", "type": "Product", "namespace": "domain-a", "entity_id": "product-a"},
            {"name": "Model-X", "type": "Product", "namespace": "domain-b", "entity_id": "product-b"},
            {"name": "Firmware-1", "type": "Firmware", "namespace": "domain-a", "entity_id": "firmware-a"},
        ],
        [{"source_entity_id": "product-a", "target_entity_id": "firmware-a", "type": "HAS_FIRMWARE"}],
        source_document="DOC-001",
        source_chunk_id="DOC-001::chunk::7",
    )
    assert len({item["entity_key"] for item in result["entities"]}) == 3
    relation = result["relationships"][0]
    assert relation["source_entity"] in {item["entity_key"] for item in result["entities"]}
    assert relation["target_entity"] == "firmware-a"
    assert relation["source_document"] == "DOC-001"
    assert relation["source_chunk_id"] == "DOC-001::chunk::7"
    assert relation["evidence_type"] == "ai_inferred"
    assert relation["review_status"] == "pending"


def test_missing_endpoint_is_fail_closed():
    result = build_graph_contract(
        [{"name": "A", "type": "Product"}],
        [{"source": "A", "target": "missing", "type": "RELATED_TO"}],
        source_document="DOC-002",
    )
    assert result["relationships"] == []


def test_ambiguous_display_name_is_fail_closed_without_explicit_id():
    result = build_graph_contract(
        [
            {"name": "Model-X", "type": "Product", "namespace": "domain-a"},
            {"name": "Model-X", "type": "Product", "namespace": "domain-b"},
            {"name": "Firmware-1", "type": "Firmware"},
        ],
        [{"source": "Model-X", "target": "Firmware-1", "type": "HAS_FIRMWARE"}],
        source_document="DOC-003",
    )
    assert result["relationships"] == []
