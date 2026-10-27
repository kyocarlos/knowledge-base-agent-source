from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools, run_agent
from src.wifi8.memory import DIGEST_HEADER, digest, history_messages
from tests.test_wifi8_agent import reply
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)


def exchange(n, sources=None):
    return [{"role": "user", "content": f"問題 {n}：NPCA 的第 {n} 個細節？"},
            {"role": "assistant", "content": f"## 結論\n\n**NPCA** 的第 {n} 個細節是 X{n}。[S1]\n\n更多說明……", **({"sources": sources} if sources else {})}]


def test_short_conversations_are_passed_through_unchanged():
    turns = exchange(1) + exchange(2)
    out = history_messages(turns)
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant"] and out[1]["content"] == turns[1]["content"]


def test_older_turns_become_one_digest_and_recent_turns_stay_verbatim():
    turns = sum((exchange(n, [f"WFA 文件 {n}"]) for n in range(1, 7)), [])  # 12 messages: 6 recent verbatim, 6 older condensed
    out = history_messages(turns)
    assert out[0]["role"] == "system" and out[0]["content"].startswith(DIGEST_HEADER)
    assert [m["role"] for m in out[1:]] == ["user", "assistant"] * 3 and out[1]["content"].startswith("問題 4")
    text = out[0]["content"]
    assert "問：問題 1：NPCA 的第 1 個細節？" in text and "答：NPCA 的第 1 個細節是 X1。" in text and "來源：WFA 文件 1" in text
    assert "[S1]" not in text and "**" not in text and "## " not in text  # citation and markdown markers are gone


def test_a_window_never_starts_with_an_answer_whose_question_was_condensed():
    turns = [{"role": "user", "content": "first"}] + exchange(1) + exchange(2) + exchange(3)  # 7 messages + 1 → odd split
    out = history_messages(turns, recent=5)
    assert out[0]["role"] == "system" and out[1]["role"] == "user"


def test_digest_is_bounded_and_keeps_the_newest_exchanges():
    turns = sum((exchange(n, ["很長的文件名稱 " * 10]) for n in range(1, 80)), [])
    text = digest(turns, limit=600)
    assert len(text) <= 600 + 40 and "第 79 個細節" in text and "第 1 個細節" not in text and "未列入" in text


def test_unanswered_question_and_garbage_turns_do_not_break_it():
    turns = [{"role": "user", "content": "只有問題"}, {"role": "tool", "content": "x"}, {"role": "user"}, "oops", {"role": "assistant", "content": 5}]
    assert digest(turns) == "" or "未取得回答" in digest(turns)
    assert history_messages(None) == [] and history_messages([]) == []
    assert isinstance(history_messages(turns, recent=1), list)


def test_the_agent_uses_it_only_when_the_flag_is_on(engine):  # noqa: F811
    search, *_ = engine
    turns = sum((exchange(n) for n in range(1, 6)), [])
    seen = {}

    def llm(*, messages, tools, tool_choice):
        seen["messages"] = messages
        return reply("ok")
    for memory in (False, True):
        settings = AgentSettings(memory=memory, grounding=False)
        run_agent("接著呢？", llm=llm, tools=WifiTools(search, settings, CitationRegistry()), settings=settings, history=turns)
        systems = [m for m in seen["messages"] if m["role"] == "system"]
        assert (len(systems) == 2) is memory and seen["messages"][-1]["content"] == "接著呢？"
        assert len([m for m in seen["messages"] if m["role"] in {"user", "assistant"}]) == 7  # 6 recent + the new question
