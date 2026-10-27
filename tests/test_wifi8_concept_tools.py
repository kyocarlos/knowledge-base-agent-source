import json

from src.wifi8.agent import CitationRegistry, AgentSettings, WifiTools, run_agent
from src.wifi8.concept_tools import CONCEPT_PROMPT, CONCEPT_TOOLS, RELATION_TYPES, key, resolve
from tests.test_wifi8_agent import ScriptedLlm, call, reply
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)

INDEX = [
    {"concept_id": "c-elr", "name": "ELR", "type": "Feature", "aliases": ["Enhanced Long Range"], "doc_count": 4},
    {"concept_id": "c-npca", "name": "NPCA", "type": "Feature", "aliases": [], "doc_count": 9},
    {"concept_id": "c-test", "name": "ELR link test", "type": "TestItem", "aliases": [], "doc_count": 1},
    {"concept_id": "c-npca2", "name": "NPCA Disabled Channel bitmap", "type": "Field", "aliases": [], "doc_count": 2},
]


class FakeConceptGraph:
    def __init__(self, index=None):
        self.index, self.calls = INDEX if index is None else index, []

    def concept_index(self, ttl=600.0):
        return self.index

    def concept_relations(self, concept_id, relation="", limit=40):
        self.calls.append(("relations", concept_id, relation))
        rows = {"c-elr": [
            {"direction": "out", "relation": "TESTED_BY", "other_id": "c-test", "other": "ELR link test", "other_type": "TestItem", "support_docs": 1, "support_windows": 1,
             "confidence": 0.9, "weak": False, "evidence": ["elr2: ELR link test verifies ELR range", "ghost: not a known document"]},
            {"direction": "in", "relation": "USES", "other_id": "c-npca", "other": "NPCA", "other_type": "Feature", "support_docs": 3, "support_windows": 3,
             "confidence": 0.8, "weak": True, "evidence": ["bcm: BCM43840 supports ELR, NPCA and DSO"]}]}.get(concept_id, [])
        return [r for r in rows if not relation or r["relation"] == relation]

    def concept_documents(self, concept_id, limit=20):
        return [{"revision_id": "elr2", "title": "ELR MRD v2", "document_role": "MRD"}]

    def concept_shared_documents(self, a, b, limit=20):
        return [{"revision_id": "bcm", "title": "BCM43840 Product Brief", "document_role": "Product Brief"}]

    def concept_common(self, a, b, limit=12):
        return [{"name": "Wi-Fi 8", "type": "Standard", "with_a": ["PART_OF"], "with_b": ["PART_OF"], "doc_count": 20}]


def make(search, graph, concepts=True):
    settings = AgentSettings(concepts=concepts)
    return WifiTools(search, settings, CitationRegistry(), graph), settings


def test_names_resolve_by_alias_plural_and_longer_name_and_prefer_documented_concepts():
    assert key("Enhanced Long-Range") == key("enhanced long range")
    assert resolve(INDEX, "enhanced long range")[0]["concept_id"] == "c-elr"
    assert resolve(INDEX, "NPCAs")[0]["concept_id"] == "c-npca"  # plural folded
    best, others = resolve(INDEX, "disabled channel")
    assert best["concept_id"] == "c-npca2" and others == []
    assert resolve(INDEX, "x")[0] is None and resolve(INDEX, "nothing like it")[0] is None


def test_relation_types_match_the_graph_writer():
    from src.wifi8.concepts import RELATION_TYPES as WRITER
    assert set(WRITER) == set(RELATION_TYPES)


def test_relations_register_evidence_as_citations_and_skip_unknown_documents(engine):  # noqa: F811
    search, *_ = engine
    tools, _ = make(search, FakeConceptGraph())
    out = tools.call("concept_relations", {"name": "enhanced long range"})
    assert out["concept"]["name"] == "ELR" and {r["relation"] for r in out["relations"]} == {"TESTED_BY", "USES"}
    tested = next(r for r in out["relations"] if r["relation"] == "TESTED_BY")
    assert tested["direction"] == "out" and "ELR → 對方" == tested["meaning"]
    assert len(tested["items"][0]["evidence"]) == 1  # the quote of an unknown document is dropped, not cited
    ref = tested["items"][0]["evidence"][0]["ref"]
    assert tools.citations.texts[ref] == "ELR link test verifies ELR range" and tools.citations.items[ref]["revision_id"] == "elr2"
    uses = next(r for r in out["relations"] if r["relation"] == "USES")
    assert uses["direction"] == "in" and uses["items"][0]["weak"] is True and out["mentioned_in"][0]["title"] == "ELR MRD v2"
    again = tools.call("concept_relations", {"name": "ELR", "relation_type": "tested_by", "direction": "out"})
    assert [r["relation"] for r in again["relations"]] == ["TESTED_BY"]
    assert again["relations"][0]["items"][0]["evidence"][0]["ref"] == ref  # the same quote keeps its number


def test_a_direction_with_no_rows_falls_back_to_both_and_says_so(engine):  # noqa: F811
    search, *_ = engine
    tools, _ = make(search, FakeConceptGraph())
    out = tools.call("concept_relations", {"name": "ELR", "relation_type": "TESTED_BY", "direction": "in"})
    assert out["relations"][0]["direction"] == "out" and "另一個方向" in out["direction_note"]
    assert "direction_note" not in tools.call("concept_relations", {"name": "ELR", "direction": "out"})


def test_bad_arguments_and_missing_concepts_give_errors_the_model_can_act_on(engine):  # noqa: F811
    search, *_ = engine
    tools, _ = make(search, FakeConceptGraph())
    assert "relation_type" in tools.call("concept_relations", {"name": "ELR", "relation_type": "LOVES"})["error"]
    missing = tools.call("concept_relations", {"name": "Quantum Router"})
    assert "找不到" in missing["error"] and "部分文件" in missing["note"]
    assert "尚未載入" in make(search, FakeConceptGraph(index=[]))[0].call("concept_relations", {"name": "ELR"})["error"]


def test_compare_reports_direct_relations_shared_documents_and_common_concepts(engine):  # noqa: F811
    search, *_ = engine
    tools, _ = make(search, FakeConceptGraph())
    out = tools.call("concept_compare", {"a": "ELR", "b": "NPCA"})
    assert out["direct_relations"][0]["relation"] == "USES" and out["direct_relations"][0]["meaning"] == "NPCA → ELR"
    assert out["shared_documents_count"] == 1 and out["common_concepts"][0]["name"] == "Wi-Fi 8"
    assert tools.call("concept_compare", {"a": "ELR", "b": "enhanced long range"})["error"]


def test_flag_off_or_no_graph_means_no_concept_tools_and_no_prompt(engine):  # noqa: F811
    search, *_ = engine
    for concepts, graph in ((False, FakeConceptGraph()), (True, None)):
        tools, settings = make(search, graph, concepts)
        seen = {}

        def llm(*, messages, tools, tool_choice):
            seen["names"] = [t["function"]["name"] for t in tools]
            seen["system"] = messages[0]["content"]
            return reply("ok")
        run_agent("q", llm=llm, tools=tools, settings=settings)
        assert "concept_relations" not in seen["names"] and CONCEPT_PROMPT not in seen["system"]
        assert tools.call("concept_relations", {"name": "ELR"})["error"].startswith("未知的工具")


def test_flag_on_offers_the_tools_and_the_answer_can_cite_the_evidence(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make(search, FakeConceptGraph())
    seen = {}

    def llm(*, messages, tools, tool_choice):
        seen.setdefault("names", [t["function"]["name"] for t in tools])
        seen.setdefault("system", messages[0]["content"])
        if not any(m.get("role") == "tool" for m in messages):
            return reply(calls=[call("concept_relations", {"name": "ELR", "relation_type": "TESTED_BY"})])
        ref = json.loads(messages[-1]["content"])["relations"][0]["items"][0]["evidence"][0]["ref"]
        return reply(f"依概念圖譜，ELR 由 ELR link test 測試 [{ref}]。")
    out = run_agent("ELR 有哪些測項？", llm=llm, tools=tools, settings=settings)
    assert {t["function"]["name"] for t in CONCEPT_TOOLS} <= set(seen["names"]) and CONCEPT_PROMPT in seen["system"]
    assert out["citations"][0]["revision_id"] == "elr2" and out["citations"][0]["content"] == "ELR link test verifies ELR range"
    assert out["trace"][0]["tool"] == "concept_relations"
