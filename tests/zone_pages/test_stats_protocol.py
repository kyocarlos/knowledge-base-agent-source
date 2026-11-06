"""The fixed order of a question about report numbers: technology, then kind of report, then project, and only then the numbers."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

from src.zone_pages import stats
from src.zone_pages.agent import ZoneAgent
from tests.zone_pages.test_stats import CAT, Catalog, WIFI_ROW


def kind(rt, *models, metric="throughput"):
    return {"products": [{"id": m, "model": m, "document_id": f"DOC-{m}"} for m in models], "metrics": [{"name": metric, "unit": "Mbps", "description": None, "numbered": False}],
            "dims": {}, "cases": [], "series": ["band"]}


FULL = {"wifi_throughput": kind("wifi_throughput", "PKE3540J", "PKE9999"), "wifi_rvr": kind("wifi_rvr", "NCM1150D2"), "cellular_throughput": kind("cellular_throughput", "SCU5050"),
        "cellular_handover": kind("cellular_handover", "SCU2050")}


def plan(**kw):
    return {"needed": True, "technology": None, "report_type": None, "products": [], "all_products": False, "metrics": [], "filters": {}, "group_by": [], "from_no": None, "to_no": None, **kw}


def test_a_question_with_no_technology_is_asked_which_whatever_it_is_about():
    for subject in ("吞吐量", "延遲", "RSSI", "通過率"):
        step = stats.next_step(plan(), FULL)
        assert "plan" not in step and step["ask"]["options"] == ["WiFi", "5G"]
        assert "WiFi 還是 5G" in step["ask"]["text"] and "目前資料庫有：" in step["ask"]["text"]
    assert stats.next_step(plan(), {"wifi_throughput": FULL["wifi_throughput"]})["ask"]["options"] == ["WiFi", "5G"]      # asked even where only one exists


def test_a_technology_with_several_projects_is_asked_which_project_next():
    step = stats.next_step(plan(technology="wifi"), FULL)
    assert step["ask"]["options"] == ["PKE3540J", "PKE9999", "全部設備"] and "設備 PKE3540J，文件 DOC-PKE3540J" in step["ask"]["text"] and "WiFi 吞吐量報告" in step["ask"]["text"]


def test_a_named_project_or_all_of_them_go_straight_to_the_numbers():
    assert stats.next_step(plan(technology="wifi", products=["PKE3540J"]), FULL)["plan"]["report_type"] == "wifi_throughput"
    assert stats.next_step(plan(technology="wifi", all_products=True), FULL)["plan"]["report_type"] == "wifi_throughput"
    assert stats.next_step(plan(technology="cellular"), FULL)["plan"]["report_type"] == "cellular_throughput"          # one project: nothing to ask


def test_a_kind_the_question_names_is_used_and_its_technology_is_known():
    assert stats.next_step(plan(report_type="wifi_rvr"), FULL)["plan"]["report_type"] == "wifi_rvr"
    assert stats.next_step(plan(report_type="cellular_handover"), FULL)["plan"]["report_type"] == "cellular_handover"
    assert "ask" in stats.next_step(plan(report_type="wifi_throughput"), FULL)                                        # known, but which of its two projects?


def test_a_device_settles_the_kind_unless_it_has_several():
    assert stats.next_step(plan(products=["SCU5050"]), FULL)["plan"]["report_type"] == "cellular_throughput"
    both = {**FULL, "wifi_rvr": kind("wifi_rvr", "PKE3540J")}
    assert stats.next_step(plan(products=["PKE3540J"]), both)["plan"]["report_type"] == "wifi_throughput"             # the general kind wins
    handover_and_rvr = {"cellular_handover": kind("cellular_handover", "X1"), "cellular_rvr": kind("cellular_rvr", "X1")}
    assert stats.next_step(plan(products=["X1"]), handover_and_rvr)["ask"]["options"] == ["5G 換手", "cellular_rvr"]


def test_a_technology_without_its_general_report_lists_what_there_is():
    only_handover = {"cellular_handover": FULL["cellular_handover"]}
    step = stats.next_step(plan(technology="cellular"), only_handover)
    assert step["ask"]["options"] == ["5G 換手"] and "5G的報告有：5G換手" in step["ask"]["text"].replace(" ", "")
    none = stats.next_step(plan(technology="wifi"), only_handover)
    assert none["ask"]["options"] == ["5G 換手"] and "沒有WiFi的測試報告數據" in none["ask"]["text"].replace(" ", "")


def test_a_kind_for_a_future_technology_follows_the_same_order():
    pon = {"pon_throughput": kind("pon_throughput", "OLT1", "OLT2")}
    assert stats.next_step(plan(), pon)["ask"]["options"] == ["WiFi", "5G", "pon"]
    assert stats.next_step(plan(technology="pon"), pon)["ask"]["options"] == ["OLT1", "OLT2", "全部設備"]


@contextmanager
def source(cat=FULL, seen=None):
    def run(**p):
        (seen if seen is not None else []).append(p)
        return {"rows": [WIFI_ROW], "truncated": False, "series": ["band"], "group_by": []}
    yield SimpleNamespace(catalog=lambda: cat, stats=run)


def test_nothing_is_fetched_until_every_question_is_answered():
    seen = []
    ask = lambda **kw: stats.ReportStats(lambda m: json.dumps(plan(**kw)), lambda: source(seen=seen)).consult("吞吐量平均是多少？")
    assert ask()["ask"] and ask(technology="wifi")["ask"] and seen == []
    done = ask(technology="wifi", products=["PKE3540J"])
    assert done["ask"] is None and done["passages"] and seen[0]["report_type"] == "wifi_throughput" and seen[0]["products"] == ["PKE3540J"]


def test_the_earlier_questions_go_to_the_planner_so_a_typed_answer_is_understood():
    prompts = []
    stats.ReportStats(lambda m: prompts.append(m) or json.dumps(plan(technology="wifi", all_products=True)), lambda: source()).consult(
        "全部設備", [{"role": "user", "content": "吞吐量平均是多少？"}, {"role": "assistant", "content": "請問 WiFi 還是 5G？"}, {"role": "user", "content": "WiFi"}])
    sent = prompts[0][-1]["content"]
    assert "前面的提問：吞吐量平均是多少？／WiFi" in sent and "目前的問題：全部設備" in sent


def test_the_agent_asks_without_calling_the_answering_model_and_each_option_completes_the_question():
    events, asked_model = [], []
    st = stats.ReportStats(lambda m: json.dumps(plan()), lambda: source())
    result = ZoneAgent(Catalog(), lambda messages: asked_model.append(messages) or "不應該被呼叫", stats=st).answer(
        task_id="t", zone_label="產品驗證專區", zone_names=["產品驗證專區"], question="延遲平均是多少？", history=[], owner={"user_id": "u"}, file_records={}, emit=events.append, with_stats=True)
    assert result["status"] == "completed" and result["citations"] == [] and result["trace"] == [{"tool": "ask_clarification"}] and asked_model == []
    assert "WiFi 還是 5G" in result["answer_main"] and "可以直接點下面的選項" in result["answer_main"]
    assert result["extension"]["followups"] == ["延遲平均是多少？（WiFi）", "延遲平均是多少？（5G）"]
    assert any(e.get("type") == "delta" for e in events)


def test_the_general_kind_is_used_only_when_it_holds_the_metric_asked_for():
    full = {**FULL, "wifi_rvr": kind("wifi_rvr", "NCM1150D2", metric="pass_rate")}
    assert stats.next_step(plan(technology="wifi", metrics=["throughput"], all_products=True), full)["plan"]["report_type"] == "wifi_throughput"
    asked = stats.next_step(plan(technology="wifi", metrics=["pass_rate"]), full)
    assert asked["ask"]["options"] == ["WiFi RvR"]                              # throughput reports have no pass rate: the user picks the kind
    assert stats.next_step(plan(technology="wifi", metrics=["unknown_metric"], all_products=True), full)["plan"]["report_type"] == "wifi_throughput"


def test_what_the_question_plainly_says_is_found_by_the_program_not_only_the_model():
    cat = {**FULL, "wifi_throughput": kind("wifi_throughput", "PKE3540J-D223", "TP-Link Archer BE800")}
    got = stats.with_hints(plan(), "吞吐量平均是多少？（WiFi）（PKE3540J）", cat)
    assert got["products"] == ["PKE3540J-D223"] and got["technology"] == "wifi" and not got["all_products"]
    assert stats.with_hints(plan(), "吞吐量平均是多少？（全部設備）", cat)["all_products"] is True
    assert stats.with_hints(plan(), "TP-Link Archer BE800 的吞吐量", cat)["products"] == ["TP-Link Archer BE800"]
    assert stats.with_hints(plan(), "吞吐量（5G）", cat)["technology"] == "cellular"
    assert stats.with_hints(plan(), "wifi 和 5G 哪個比較快", cat)["technology"] is None                     # both words: left to be asked
    assert stats.with_hints(plan(technology="wifi"), "5G", cat)["technology"] == "wifi"                        # what the model read is kept
    assert stats.with_hints(plan(), "link 的平均", cat)["products"] == []                                      # a word with no digit is not a device
    assert stats.with_hints(plan(products=["X9"]), "PKE3540J", cat)["products"] == ["X9", "PKE3540J-D223"]


def test_a_short_device_name_typed_as_the_answer_goes_through_to_the_numbers():
    cat = {**FULL, "wifi_throughput": kind("wifi_throughput", "PKE3540J-D223", "TP-Link Archer BE800")}
    seen = []
    done = stats.ReportStats(lambda m: json.dumps(plan(technology="wifi")), lambda: source(cat=cat, seen=seen)).consult("吞吐量平均是多少？（WiFi）（PKE3540J）")
    assert done["ask"] is None and done["passages"] and seen[0]["products"] == ["PKE3540J-D223"]


def test_a_question_back_is_not_shown_as_an_answer_without_support():
    st = stats.ReportStats(lambda m: json.dumps(plan(technology="cellular")), lambda: source(cat={"cellular_handover": FULL["cellular_handover"]}))
    result = ZoneAgent(Catalog(), lambda messages: "x", stats=st).answer(task_id="t", zone_label="z", zone_names=["z"], question="吞吐量平均是多少？（5G）", history=[], owner={}, file_records={},
                                                                         emit=lambda e: None, with_stats=True)
    assert result["grounding"]["summary"]["claims"] == 0 and result["grounding"]["summary"]["claims_cited"] == 0 and result["grounding"]["flagged"] == []
    assert result["extension"]["followups"] == ["吞吐量平均是多少？（5G 換手）"]                  # the technology is in the choice already: not "（5G）（5G 換手）"
