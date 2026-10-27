import json
from types import SimpleNamespace

import pytest

from src.wifi8.agent import GRAPH_TOOLS, TOOLS, AgentSettings, CitationRegistry, GraphCitations, WifiTools, run_agent
from src.wifi8.extension import DISCLAIMER, EXTENSION_RULES, RULE7_ORIGINAL, extended_prompt, split_answer
from src.wifi8.graph import Wifi8Graph
from tests.test_wifi8_agent import ScriptedLlm, call, reply
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)

FULL = f"""ELR 可延伸上行距離 [S1]。

## 延伸知識
### 相關主題與文件
共用主題的文件有 MAPC MRD [G1]。
### 一般知識補充
（{DISCLAIMER}）
上行距離受發射功率與天線增益限制。
### 你可能還想問
- NPCA 與 ELR 如何搭配？
2. ELR 的認證測項有哪些？
- 第三題
- 第四題不應出現
"""


def test_split_separates_main_and_every_extension_part():
    main, ext = split_answer(FULL)
    assert main == "ELR 可延伸上行距離 [S1]。"
    assert "MAPC MRD [G1]" in ext["related"] and "發射功率" in ext["general"]
    assert ext["followups"] == ["NPCA 與 ELR 如何搭配？", "ELR 的認證測項有哪些？", "第三題"] and ext["warnings"] == []


def test_no_extension_heading_means_nothing_to_split():
    assert split_answer("只有主體 [S1]。") == ("只有主體 [S1]。", None)
    assert split_answer("") == ("", None)
    assert split_answer("主體\n## 延伸知識\n") == ("主體", None)  # heading without content


def test_general_knowledge_always_carries_the_label_and_citations_are_flagged():
    _, ext = split_answer("主體\n## 延伸知識\n### 一般知識補充\nWi-Fi 常用 OFDMA [S2]。")
    assert ext["general"].startswith(f"（{DISCLAIMER}）") and ext["warnings"] == ["general_knowledge_has_citation"]


def test_prompt_narrows_rule_seven_only_when_extended():
    assert RULE7_ORIGINAL in __import__("src.wifi8.agent", fromlist=["SYSTEM_PROMPT"]).SYSTEM_PROMPT
    from src.wifi8.agent import SYSTEM_PROMPT
    ext = extended_prompt(SYSTEM_PROMPT)
    assert RULE7_ORIGINAL not in ext and EXTENSION_RULES in ext and "一般知識只能放在最後的「延伸知識」" in ext


class FakeGraph:
    def __init__(self):
        self.calls = []

    def related_documents(self, rid, limit=8):
        self.calls.append(("related_documents", rid))
        return [{"revision_id": "r2", "title": "MAPC MRD", "document_role": "MRD", "publisher": "WFA", "lifecycle": "current", "shared_topics": ["Wi-Fi 8"], "shared": 1}]

    def topic_neighbours(self, topic, limit=8):
        self.calls.append(("topic_neighbours", topic))
        return [{"topic": "MRD", "documents": 5}]

    def topic_documents(self, topic, limit=8):
        return [{"revision_id": "r3", "title": "NPCA doc", "document_role": "MRD", "publisher": "WFA", "lifecycle": "current", "topic": topic}]

    def timeline(self, rid, limit=12):
        return [{"revision_id": "r1", "title": "v1", "lifecycle": "superseded"}, {"revision_id": rid, "title": "v2", "lifecycle": "current"}]


def make_tools(search, graph=None, extension=True):
    settings = AgentSettings(extension=extension)
    return WifiTools(search, settings, CitationRegistry(), graph), settings


def test_flag_off_keeps_prompt_tools_and_result_unchanged(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make_tools(search, FakeGraph(), extension=False)
    llm = ScriptedLlm(reply(FULL))
    out = run_agent("q", llm=llm, tools=tools, settings=settings)
    request = llm.requests[0]
    assert RULE7_ORIGINAL in request["messages"][0]["content"] and "延伸知識（本次已啟用）" not in request["messages"][0]["content"]
    assert "extension" not in out and "answer_main" not in out and out["answer"] == FULL


def test_extension_on_exposes_graph_tools_and_returns_split_result(engine):  # noqa: F811
    search, *_ = engine
    graph = FakeGraph()
    tools, settings = make_tools(search, graph)
    seen = {}

    def llm(*, messages, tools, tool_choice):
        seen.setdefault("tools", [t["function"]["name"] for t in tools])
        seen["system"] = messages[0]["content"]
        if not any(m.get("role") == "tool" for m in messages):
            return reply(calls=[call("graph_related", {"revision_id": "r1"})])
        return reply(FULL)
    out = run_agent("ELR 是什麼？", llm=llm, tools=tools, settings=settings)
    assert {"graph_related", "graph_timeline"} <= set(seen["tools"]) and "延伸知識（本次已啟用）" in seen["system"]
    assert graph.calls == [("related_documents", "r1")]
    assert out["answer_main"] == "ELR 可延伸上行距離 [S1]。" and out["extension"]["followups"][0].startswith("NPCA")
    assert [g["ref"] for g in out["graph_citations"]] == ["G1"] and out["graph_citations"][0]["title"] == "MAPC MRD" and out["graph_citations"][0]["origin"] == "graph"


def test_grounding_only_sees_the_main_answer(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make_tools(search, FakeGraph())
    seen = {}
    import src.wifi8.agent as agent_module
    original = agent_module.ground
    agent_module.ground = lambda result, *a, **k: seen.setdefault("answer", result["answer"]) and {"summary": {}}
    try:
        run_agent("q", llm=ScriptedLlm(reply(FULL)), tools=tools, settings=settings)
    finally:
        agent_module.ground = original
    assert "延伸知識" not in seen["answer"] and "發射功率" not in seen["answer"]


def test_without_a_graph_the_tools_are_not_offered(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make_tools(search, None)
    names = {}

    def llm(*, messages, tools, tool_choice):
        names["n"] = {t["function"]["name"] for t in tools}
        return reply("答案 [S1]。")
    run_agent("q", llm=llm, tools=tools, settings=settings)
    assert not names["n"] & {"graph_related", "graph_timeline"} and names["n"] == {t["function"]["name"] for t in TOOLS}
    assert tools.call("graph_related", {"topic": "ELR"}).get("error")  # also refused if called anyway


def test_graph_tool_results_register_stable_refs(engine):  # noqa: F811
    search, *_ = engine
    tools, _ = make_tools(search, FakeGraph())
    a = tools.call("graph_related", {"topic": "NPCA"})
    b = tools.call("graph_related", {"topic": "NPCA"})
    assert a["related_topics"][0]["ref"] == b["related_topics"][0]["ref"] == "G1" and a["documents"][0]["ref"] == "G2"
    assert tools.call("graph_related", {}).get("error")
    assert [v["revision_id"] for v in tools.call("graph_timeline", {"revision_id": "r9"})["versions"]] == ["r1", "r9"]


class FakeSession:
    def __init__(self, rows, log):
        self.rows, self.log = rows, log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, query, **params):
        self.log.append((str(getattr(query, "text", query)), params))
        return [self.rows]


def test_graph_queries_are_fixed_templates_read_only_and_bounded():
    log = []
    modes = []

    class Driver:
        def session(self, **kw):
            modes.append(kw)
            return FakeSession({"revision_id": "x"}, log)
    graph = Wifi8Graph(Driver(), max_rows=5)
    graph.related_documents("r1", limit=500)
    graph.topic_documents("NPCA'; MATCH (n) DETACH DELETE n //")
    assert all(m["default_access_mode"] == "READ" for m in modes)
    assert log[0][1]["limit"] == 5 and log[0][1]["rid"] == "r1"
    assert log[1][1]["topic"].startswith("NPCA'") and "DETACH DELETE" not in log[1][0]  # user text only ever travels as a parameter
    assert all(("CREATE" not in q.upper() and "MERGE" not in q.upper() and "DELETE" not in q.upper()) for q, _ in log)


def test_graph_citations_are_deduplicated():
    g = GraphCitations()
    assert g.add("document", "r1", title="a") == g.add("document", "r1", title="a") == "G1" and g.add("topic", "r1") == "G2"
