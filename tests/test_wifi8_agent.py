import json
from types import SimpleNamespace

import pytest

from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools, run_agent
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)


def reply(content="", calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls or []))])


def call(name, args, cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedLlm:
    def __init__(self, *steps):
        self.steps = list(steps)
        self.requests = []

    def __call__(self, *, messages, tools, tool_choice):
        self.requests.append({"messages": list(messages), "tool_choice": tool_choice})
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step


@pytest.fixture
def tools(engine):  # noqa: F811
    search, *_ = engine
    return WifiTools(search, AgentSettings(), CitationRegistry())


def test_agent_searches_then_answers_with_citations(tools):
    def final(messages):
        result = json.loads(messages[-1]["content"])
        ref = result["hits"][0]["ref"]
        return reply(f"ELR 可延伸上行距離 [{ref}]。另見 [S99]。")
    llm = ScriptedLlm(reply(calls=[call("search_wifi", {"query": "ELR uplink range"})]), final)
    out = run_agent("ELR 是什麼？", llm=llm, tools=tools, settings=AgentSettings())
    assert out["stop_reason"] == "answered"
    assert [c["source"] for c in out["citations"]] == ["ELR MRD v2"]  # unknown [S99] is not invented
    assert out["trace"][0]["tool"] == "search_wifi" and "ELR MRD v2" in out["trace"][0]["result_summary"]
    assert llm.requests[0]["messages"][0]["role"] == "system"
    tool_msg = llm.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "c1"


def test_step_limit_forces_final_answer_without_tools(tools):
    looping = [reply(calls=[call("zone_overview", {}, f"c{i}")]) for i in range(2)]
    llm = ScriptedLlm(*looping, reply("根據目前結果作答。"))
    out = run_agent("專區有哪些文件？", llm=llm, tools=tools, settings=AgentSettings(max_steps=2))
    assert out["stop_reason"] == "max_steps" and out["answer"] == "根據目前結果作答。"
    assert llm.requests[-1]["tool_choice"] == "none"
    assert len(out["trace"]) == 2


def test_time_budget_stops_the_loop(tools):
    ticks = iter([0, 0, 0, 100, 100, 100, 100])
    llm = ScriptedLlm(reply(calls=[call("zone_overview", {})]), reply("時間到，先回答。"))
    out = run_agent("q", llm=llm, tools=tools, settings=AgentSettings(time_budget_seconds=10), clock=lambda: next(ticks))
    assert out["stop_reason"] == "time_budget" and llm.requests[-1]["tool_choice"] == "none"


def test_bad_arguments_and_unknown_tools_are_reported_to_the_model(tools):
    bad = {"id": "x", "type": "function", "function": {"name": "search_wifi", "arguments": "{not json"}}
    llm = ScriptedLlm(reply(calls=[bad, call("drop_table", {}, "y"), call("read_document", {"wrong": 1}, "z")]), reply("ok"))
    out = run_agent("q", llm=llm, tools=tools, settings=AgentSettings())
    summaries = [t["result_summary"] for t in out["trace"]]
    assert summaries[0].startswith("錯誤：工具參數不是 JSON")
    assert "未知的工具" in summaries[1] and "參數錯誤" in summaries[2]


def test_document_tools(tools):
    versions = tools.list_versions("elr2")["versions"]
    assert {v["revision_id"] for v in versions} == {"elr1", "elr2"}
    assert tools.get_document(wfa_document_id="104438")["documents"][0]["title"] == "ELR MRD v2"
    page = tools.read_document("big", start=1, count=3)
    assert len(page["parts"]) == 3 and page["next_start"] == 4 and page["parts"][0]["ref"].startswith("S")
    assert tools.list_documents(publisher="WFA")["total"] == 1  # superseded v1 hidden by default
    assert tools.list_documents(publisher="WFA", include_history=True)["total"] == 2
    overview = tools.zone_overview()
    assert overview["documents"] == 5 and overview["current_documents"] == 4
    assert sum(n for _, n in overview["by_document_role"]) == overview["current_documents"]
    assert sum(n for _, n in overview["by_publisher"]) == overview["current_documents"]


def test_agent_api_binds_results_to_the_asker(monkeypatch, tmp_path):
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from src.web_api import tasks, wifi8_routes

    monkeypatch.setenv("KM_WIFI8_ROOT", str(tmp_path / "wifi8"))
    sent = []
    monkeypatch.setattr(tasks.celery_app, "send_task", lambda name, args, queue: sent.append((name, args, queue)) or SimpleNamespace(id="t-1"))
    stored = {"t-1": {"owner": {"user_id": "u1", "instance_id": "test"}, "status": "completed", "answer": "ok [S1]"}}

    class FakeResult:
        def __init__(self, task_id, app=None):
            self.task_id = task_id

        def ready(self):
            return self.task_id in stored

        @property
        def result(self):
            return stored[self.task_id]

    monkeypatch.setattr("celery.result.AsyncResult", FakeResult)
    app = FastAPI()
    who = {"sub": "u1"}

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.km_identity = {"sub": who["sub"], "instance_id": "test"}
        return await call_next(request)

    app.include_router(wifi8_routes.router)
    client = TestClient(app)
    response = client.post("/api/wifi8/agent", json={"question": " ELR 是什麼？ ", "history": [{"role": "user", "content": "hi"}]})
    assert response.status_code == 202 and response.json()["task_id"] == "t-1"
    name, args, queue = sent[0]
    assert name == "tasks.wifi8_agent_task" and queue == "search"
    assert args[0] == "ELR 是什麼？" and args[2] == {"user_id": "u1", "instance_id": "test"}
    assert client.get("/api/wifi8/agent/t-1").json()["answer"] == "ok [S1]"
    assert "owner" not in client.get("/api/wifi8/agent/t-1").json()
    assert client.get("/api/wifi8/agent/unknown").json()["status"] == "pending"
    who["sub"] = "u2"
    assert client.get("/api/wifi8/agent/t-1").status_code == 404
    assert client.post("/api/wifi8/agent", json={"question": "x" * 2001}).status_code == 422
    assert client.post("/api/wifi8/agent", json={"question": "q", "history": [{"role": "system", "content": "x"}]}).status_code == 422


DBE_CHUNK = (
    "Dynamic Bandwidth Expansion (DBE) mode allows a UHR AP to dynamically operate with an expanded bandwidth "
    "(referred to as DBE bandwidth) greater than the BSS bandwidth, for UHR STAs that support DBE. The AP performs "
    "enablement, disablement and parameters update for DBE mode using the enhanced critical update mechanism and "
    "supports indicating any punctured sub-channels within the DBE bandwidth using a DBE Disabled Subchannel Bitmap. "
    "A UHR STA enables or disables DBE mode with the AP using the operating mode and parameters (OMP) update mechanism. "
    "While DBE mode is enabled in the BSS, the AP and the STAs that have enabled DBE mode can use up to the DBE "
    "bandwidth for PPDU exchanges between them.\nFeature\nDBE is optional for APs, and only applicable to 5 GHz and "
    "6 GHz band APs. If WPA3-Enterprise is implemented, the AP shall implement DBE.\nAn AP shall indicate support for "
    "DBE mode and include DBE capability parameters in its UHR capabilities as defined in subclause 37.27 of [2]."
)


@pytest.mark.parametrize("query", ["DBE（Dynamic Bandwidth Expansion）是什麼？什麼情況下 AP 必須實作？",
                                   "DBE AP must implement mandatory implementation conditions", "WPA3-Enterprise"])
def test_excerpt_keeps_query_relevant_sentences_beyond_the_head(query):
    from src.wifi8.agent import excerpt
    text, cut = excerpt(DBE_CHUNK, query, 700)
    assert cut and len(text) <= 700
    assert "If WPA3-Enterprise is implemented, the AP shall implement DBE." in text
    assert DBE_CHUNK[:700] not in text  # not a plain head cut


def test_excerpt_short_text_and_no_match_fallbacks():
    from src.wifi8.agent import excerpt
    assert excerpt("short", "anything", 100) == ("short", False)
    text, cut = excerpt("alpha beta. " * 50, "zzz-unrelated", 50)
    assert cut and text.startswith("alpha beta.") and text.endswith("…") and len(text) <= 50
    long_sentence = "NPCA " + "x" * 300
    text, cut = excerpt(long_sentence + ". other sentence here.", "NPCA", 100)
    assert cut and text.startswith("NPCA") and len(text) <= 100


def test_tools_mark_excerpts_and_read_document_accepts_focus(tools):
    from src.wifi8.agent import AgentSettings
    tools.settings = AgentSettings(snippet_chars=60, read_chars=60)
    hit = tools.search_wifi("ELR uplink range")["hits"][0]
    assert len(hit["text"]) <= 60 and (hit.get("excerpt") is True) == (hit.get("chars", 0) > 60)
    part = tools.read_document("big", start=1, count=1, query="segment")["parts"][0]
    assert len(part["text"]) <= 60


def test_agent_result_carries_grounding_and_failures_do_not_hide_the_answer(tools, monkeypatch):
    llm = ScriptedLlm(reply(calls=[call("search_wifi", {"query": "ELR uplink range"})]),
                      lambda messages: reply("ELR 改善上行距離，速率 9.99 Mbps。[S1]"))
    out = run_agent("ELR?", llm=llm, tools=tools, settings=AgentSettings())
    g = out["grounding"]["summary"]
    assert g["claims"] == 1 and g["claims_cited"] == 1 and g["values_not_found"] == 1  # 9.99 Mbps is not in the source

    llm = ScriptedLlm(reply("沒有引用的回答。"))
    assert "grounding" not in run_agent("q", llm=llm, tools=tools, settings=AgentSettings(grounding=False))

    import src.wifi8.grounding as grounding
    monkeypatch.setattr(grounding, "check_answer", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    out = run_agent("q", llm=ScriptedLlm(reply("答案仍然顯示。")), tools=tools, settings=AgentSettings())
    assert out["answer"] == "答案仍然顯示。" and out["grounding"]["error"].startswith("ValueError")
