from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools, run_agent
from tests.test_wifi8_agent import call, reply
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)


def make(search):
    settings = AgentSettings(grounding=False, extension=False)
    return WifiTools(search, settings, CitationRegistry()), settings


class StreamingLlm:
    """Speaks like the streaming client: pushes text to on_delta while it builds the same message object."""
    def __init__(self, *steps):
        self.steps, self.kwargs = list(steps), []

    def __call__(self, *, messages, tools, tool_choice, on_delta=None):
        self.kwargs.append({"on_delta": on_delta is not None})
        text, calls = self.steps.pop(0)
        for piece in text:
            on_delta and on_delta(piece)
        return reply("".join(text), calls)


def test_answer_text_is_streamed_and_tool_progress_is_reported(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make(search)
    events = []
    llm = StreamingLlm(([], [call("search_wifi", {"query": "ELR"})]), (["ELR ", "可延伸", "上行距離。"], []))
    out = run_agent("ELR 是什麼？", llm=llm, tools=tools, settings=settings, emit=events.append)
    assert [e["type"] for e in events] == ["tool", "delta", "delta", "delta"] and events[0]["tool"] == "search_wifi" and events[0]["label"] == "檢索文件段落"
    assert "".join(e["text"] for e in events if e["type"] == "delta") == out["answer"] == "ELR 可延伸上行距離。"
    assert all(k["on_delta"] for k in llm.kwargs)


def test_text_before_tool_calls_is_reset_so_the_client_does_not_keep_it(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make(search)
    events = []
    llm = StreamingLlm((["我先查一下。"], [call("search_wifi", {"query": "ELR"})]), (["答案"], []))
    run_agent("q", llm=llm, tools=tools, settings=settings, emit=events.append)
    assert [e["type"] for e in events] == ["delta", "reset", "tool", "delta"]


def test_without_emit_the_llm_is_called_exactly_as_before(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make(search)
    seen = []

    def llm(*, messages, tools, tool_choice):  # no on_delta parameter at all
        seen.append(tool_choice)
        return reply("ok")
    assert run_agent("q", llm=llm, tools=tools, settings=settings)["answer"] == "ok" and seen == ["auto"]


def test_a_failing_event_sink_never_breaks_the_answer(engine):  # noqa: F811
    search, *_ = engine
    tools, settings = make(search)

    def broken(event):
        raise RuntimeError("redis down")
    out = run_agent("q", llm=StreamingLlm((["好"], [])), tools=tools, settings=settings, emit=broken)
    assert out["answer"] == "好"
