"""A question that could mean WiFi or 5G Throughput is asked back, not answered with one of them picked for the user."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

from src.zone_pages import stats
from src.zone_pages.agent import ZoneAgent
from tests.zone_pages.test_stats import CAT, Catalog, WIFI_ROW

CELLULAR = {"products": [{"id": "SCU5050", "model": "SCU5050", "document_id": "SIT-TR-SC-NR-Throughput-SCU5050"}],
            "metrics": [{"name": "throughput", "unit": "Mbps", "description": None, "numbered": False}], "dims": {"band": ["n78"], "direction": ["dl"]}, "cases": [],
            "series": ["band", "center_freq_mhz", "bandwidth_mhz", "time_slot", "direction", "protocol", "traffic_mode", "statistic"]}
BOTH = {"wifi_throughput": CAT["wifi_throughput"], "cellular_throughput": CELLULAR}


def reply(**kw):
    return json.dumps({"needed": True, "report_type": None, "clarify": ["wifi_throughput", "cellular_throughput"], "products": [], "metrics": [], "filters": {}, "group_by": [],
                       "from_no": None, "to_no": None, **kw})


@contextmanager
def source(cat=BOTH, seen=None):
    def run(**p):
        (seen if seen is not None else []).append(p)
        return {"rows": [WIFI_ROW], "truncated": False, "series": ["band"], "group_by": []}
    yield SimpleNamespace(catalog=lambda: cat, stats=run)


def test_two_types_the_question_does_not_choose_between_are_asked_back():
    seen = []
    got = stats.ReportStats(lambda m: reply(), lambda: source(seen=seen)).consult("吞吐量平均是多少？")
    assert got["clarify"] == ["wifi_throughput", "cellular_throughput"] and got["passages"] == [] and seen == []      # nothing is queried
    assert set(got["labels"]) == {"wifi_throughput", "cellular_throughput"}


def test_the_model_only_proposes_what_the_catalog_and_the_device_allow():
    plan = lambda **kw: {"needed": True, "clarify": ["wifi_throughput", "cellular_throughput"], "products": [], **kw}
    assert stats.clarification(plan(), BOTH) == ["wifi_throughput", "cellular_throughput"]
    assert stats.clarification(plan(clarify=["wifi_throughput"]), BOTH) == []                                  # one candidate is no question
    assert stats.clarification(plan(clarify=["wifi_throughput", "nope"]), BOTH) == []                          # a type the database does not hold
    assert stats.clarification(plan(), {"wifi_throughput": CAT["wifi_throughput"]}) == []                      # only one type exists
    assert stats.clarification(plan(products=["PKE3540J"]), BOTH) == []                                        # a device of one type settles it
    assert stats.clarification(plan(products=["pke3540"]), BOTH) == []
    assert stats.clarification(plan(products=["SCU5050"]), BOTH) == []


def test_a_named_device_is_answered_without_asking():
    seen = []
    got = stats.ReportStats(lambda m: reply(products=["PKE3540J"], report_type="wifi_throughput"), lambda: source(seen=seen)).consult("PKE3540J 吞吐量平均？")
    assert got["clarify"] == [] and got["passages"] and seen[0]["report_type"] == "wifi_throughput"


def test_the_previous_question_goes_to_the_planner_so_a_one_word_reply_is_understood():
    prompts = []
    stats.ReportStats(lambda m: prompts.append(m) or reply(clarify=[], report_type="wifi_throughput"), lambda: source()).consult(
        "WiFi", [{"role": "user", "content": "吞吐量平均是多少？"}, {"role": "assistant", "content": "請問要查哪一種？"}])
    assert "前一個提問：吞吐量平均是多少？" in prompts[0][-1]["content"] and "目前的問題：WiFi" in prompts[0][-1]["content"]


def test_the_agent_asks_instead_of_answering_and_offers_each_choice_as_a_follow_up():
    events, asked_model = [], []
    st = stats.ReportStats(lambda m: reply(), lambda: source())
    result = ZoneAgent(Catalog(), lambda messages: asked_model.append(messages) or "不應該被呼叫", stats=st).answer(
        task_id="t", zone_label="產品驗證專區", zone_names=["產品驗證專區"], question="吞吐量平均是多少？", history=[], owner={"user_id": "u"}, file_records={},
        emit=events.append, with_stats=True)
    assert result["status"] == "completed" and result["citations"] == [] and result["trace"] == [{"tool": "ask_clarification"}]
    assert "「WiFi 吞吐量」、「5G 吞吐量」" in result["answer_main"] and "請問要查哪一種" in result["answer_main"]
    assert result["extension"]["followups"] == ["吞吐量平均是多少？（WiFi 吞吐量）", "吞吐量平均是多少？（5G 吞吐量）"]
    assert asked_model == []                                                                            # the answering model is not called for a question back
    assert any(e.get("type") == "delta" for e in events)
