import pytest

from src.wifi8.agent import AgentSettings, CitationRegistry, WifiTools, run_agent
from src.wifi8.listing import LIST_PROMPT, hints, infer_filters
from tests.test_wifi8_agent import call, reply
from tests.test_wifi8_search import engine  # noqa: F401  (fixture)

PUBLISHERS = {"WFA", "arXiv", "Wi-Fi NOW", "Intel", "Qualcomm", "Broadcom", "來源待確認", "RF Wireless World"}
ROLES = {"Research Paper", "Research or Technical Paper", "Meeting Minutes", "Meeting Agenda", "Certification Test Case", "Industry White Paper"}


@pytest.mark.parametrize("question, expected", [
    ("專區裡有哪些 arXiv 論文討論 Coordinated Spatial Reuse？請列出標題。", {"publisher": "arXiv", "document_roles": ["Research Paper", "Research or Technical Paper"]}),
    ("專區收錄了哪些 Qualcomm 的文件？", {"publisher": "Qualcomm"}),
    ("有哪些 WFA 會議紀錄提到 NPCA？", {"publisher": "WFA", "document_roles": ["Meeting Minutes"]}),
    ("哪些議程談到 DSO？", {"document_roles": ["Meeting Agenda"]}),
    ("專區裡有哪些文件主要在談 ELR？", {}),                                # nothing named: nothing applied
    ("比較 Qualcomm 與 Broadcom 的 Wi-Fi 8 文件", {}),                      # two publishers = a comparison
    ("Intelligent surfaces 的文件有哪些？", {}),                            # "Intel" inside another word
    ("Wi-Fi NOW 上有哪些文章？", {"publisher": "Wi-Fi NOW"}),               # the longer name, not a second match
    ("", {}), (None, {}),
])
def test_filters_are_taken_only_from_what_the_question_names(question, expected):
    assert infer_filters(question, PUBLISHERS, ROLES) == expected


def test_only_roles_the_zone_has_are_used():
    assert infer_filters("有哪些白皮書？", PUBLISHERS, {"Meeting Minutes"}) == {}
    assert infer_filters("有哪些白皮書？", PUBLISHERS, ROLES) == {"document_roles": ["Industry White Paper"]}


def test_every_alias_in_the_data_file_points_to_known_role_names():
    data = hints()
    assert data["default_limit"] >= 15 and data["role_aliases"]
    assert all(isinstance(v, list) and v for v in data["role_aliases"].values())


class FakeSearch:
    """Records the options find_documents hands to the engine; the document list is fixed."""
    def __init__(self, real):
        self.real, self.seen = real, []

    def __getattr__(self, name):
        return getattr(self.real, name)

    def documents(self, query, options=None, *, limit=15, candidates=200):
        self.seen.append((options, limit))
        return self.real.documents(query, options, limit=limit, candidates=candidates)


def make(engine, assist, question):  # noqa: F811
    search, *_ = engine
    fake = FakeSearch(search)
    tools = WifiTools(fake, AgentSettings(list_assist=assist, grounding=False), CitationRegistry())
    tools.question = question
    return tools, fake


def test_flag_off_find_documents_behaves_as_before(engine):  # noqa: F811
    tools, fake = make(engine, False, "有哪些 Broadcom 文件？")
    out = tools.call("find_documents", {"query": "BCM43840"})
    options, limit = fake.seen[0]
    assert options.publishers == () and options.document_roles == () and limit == 15
    assert "inferred_filters" not in out and "more_available" not in out


def test_flag_on_applies_what_the_question_names_and_says_so(engine):  # noqa: F811
    tools, fake = make(engine, True, "有哪些 Broadcom 文件？")
    out = tools.call("find_documents", {"query": "BCM43840"})
    options, limit = fake.seen[0]
    assert options.publishers == ("Broadcom",) and limit == hints()["default_limit"]
    assert out["inferred_filters"] == {"publisher": "Broadcom"} and [d["publisher"] for d in out["documents"]] == ["Broadcom"]


def test_the_models_own_filter_and_all_documents_win(engine):  # noqa: F811
    tools, fake = make(engine, True, "有哪些 Broadcom 文件？")
    out = tools.call("find_documents", {"query": "ELR", "publisher": "WFA"})
    assert fake.seen[0][0].publishers == ("WFA",) and "publisher" not in out.get("inferred_filters", {})
    tools.call("find_documents", {"query": "ELR", "all_documents": True})
    assert fake.seen[1][0].publishers == () and "inferred_filters" not in tools.call("find_documents", {"query": "ELR", "all_documents": True})


def test_truncation_is_reported_only_when_documents_were_left_out(engine):  # noqa: F811
    tools, _ = make(engine, True, "專區有哪些文件？")
    few = tools.call("find_documents", {"query": "network", "limit": 1})
    assert few["more_available"] is True and "limit" in few["more_note"]
    all_ = tools.call("find_documents", {"query": "network", "limit": 30})
    assert all_["count"] == all_["documents_found"] and "more_available" not in all_


def test_prompt_only_when_enabled(engine):  # noqa: F811
    for assist in (False, True):
        tools, _ = make(engine, assist, "q")
        seen = {}

        def llm(*, messages, tools, tool_choice):
            seen["system"] = messages[0]["content"]
            return reply("ok")
        run_agent("q", llm=llm, tools=tools, settings=tools.settings)
        assert (LIST_PROMPT in seen["system"]) is assist
