"""An answer built from the database's numbers says first which kind of report, device and document they come from."""
import json

from src.zone_pages import stats
from src.zone_pages.agent import ZoneAgent
from tests.zone_pages.test_stats import CAT, Catalog, WIFI_ROW, XN_ROW, fake_source, plan_reply

SCOPE = "設備 PKE3540J，WiFi 吞吐量報告 SIT-TR-WL-Throughput-PKE3540J"


def ask(complete, rows=None):
    st = stats.ReportStats(lambda m: plan_reply(), lambda: fake_source(rows=rows))
    return ZoneAgent(Catalog(), complete, stats=st).answer(task_id="t", zone_label="產品驗證專區", zone_names=["產品驗證專區"], question="5GHz 80MHz 下行平均吞吐量？", history=[], owner={},
                                                           file_records={}, emit=lambda e: None, with_stats=True)


def test_the_passage_names_the_report_type_the_device_and_the_document():
    got = stats.ReportStats(lambda m: plan_reply(), lambda: fake_source()).consult("?")["passages"][0]
    assert got["scope"] == SCOPE and got["content"].startswith(f"資料來源：{SCOPE}\n")
    two = stats.ReportStats(lambda m: plan_reply(), lambda: fake_source(rows=[WIFI_ROW, XN_ROW])).consult("?")["passages"][0]
    assert two["scope"] == SCOPE + "；設備 SCU2050，5G 換手報告 SIT-SR-SC-NR-Handover-SCU2050"


def test_the_answer_opens_with_that_scope_whatever_the_model_wrote():
    result = ask(lambda messages: "平均 800 Mbps [S1]。")
    assert result["answer_main"].startswith(f"**依據：{SCOPE}**\n\n平均 800 Mbps")
    assert result["grounding"]["summary"]["values_not_found"] == 0


def test_no_line_is_added_when_the_numbers_were_not_used_or_there_were_none():
    assert not ask(lambda messages: "只有文字說明 [S2]。")["answer_main"].startswith("**依據")
    assert not ask(lambda messages: "在這個專區的資料裡找不到相關內容。")["answer_main"].startswith("**依據")
    assert "沒有符合此查詢的數據" in stats.ReportStats(lambda m: plan_reply(), lambda: fake_source(rows=[])).consult("?")["passages"][0]["content"]
    assert stats.ReportStats(lambda m: plan_reply(), lambda: fake_source(rows=[])).consult("?")["passages"][0]["scope"] is None


def test_a_statistic_filter_is_dropped_where_the_report_has_only_one_statistic():
    cat = {"cellular_handover": {**CAT["cellular_handover"], "dims": {"band": ["n77"], "statistic": ["average"]}}}
    plan = {"needed": True, "report_type": "cellular_handover", "filters": {"statistic": "average", "band": "n77"}}
    assert stats.to_query(plan, cat)["filters"] == {"band": "n77"}
    many = {"cellular_handover": {**cat["cellular_handover"], "dims": {"statistic": ["average", "peak"]}}}
    assert stats.to_query({"needed": True, "report_type": "cellular_handover", "filters": {"statistic": "peak"}}, many)["filters"] == {"statistic": "peak"}


NAMED = {"wifi_throughput": {**CAT["wifi_throughput"], "products": [
    {"id": "PKE3540J", "model": "PKE3540J", "document_id": "DOC-A", "project_code": "PRJ-001", "project_name": "第一案", "case_name": "整機測試", "task_name": "吞吐量"},
    {"id": "PKE9999", "model": "PKE9999", "document_id": "DOC-B", "project_code": "PRJ-002", "project_name": "第二案", "case_name": None, "task_name": None}]}}


def test_the_project_named_by_csit_leads_the_scope_and_the_questions_back():
    row = {**WIFI_ROW, "document_id": "DOC-A"}
    assert stats.scope_of([row], NAMED) == "案子 第一案（PRJ-001），測試案例 整機測試，設備 PKE3540J，WiFi 吞吐量報告 DOC-A"
    old = {"wifi_throughput": {**NAMED["wifi_throughput"], "products": [{"id": "P", "model": "P", "document_id": "DOC-A", "project_code": "PRJ-001", "project_name": None, "case_name": None}]}}
    assert stats.scope_of([row], old) == "案子 PRJ-001，設備 PKE3540J，WiFi 吞吐量報告 DOC-A"            # a report ingested before the names were kept: the number alone
    step = stats.next_step({"needed": True, "technology": "wifi", "report_type": None, "products": [], "all_products": False, "metrics": []}, NAMED)
    assert step["ask"]["options"] == ["PKE3540J・第一案", "PKE9999・第二案", "全部設備"]
    assert "案子 第一案（PRJ-001），設備 PKE3540J，文件 DOC-A" in step["ask"]["text"]


def test_a_project_named_in_the_question_settles_the_device_when_the_name_is_unique():
    plan = {"needed": True, "technology": None, "report_type": None, "products": [], "all_products": False, "metrics": []}
    assert stats.with_hints(plan, "第二案的吞吐量", NAMED)["products"] == ["PKE9999"]
    assert stats.with_hints(plan, "吞吐量（PKE3540J・第一案）", NAMED)["products"] == ["PKE3540J"]
    same = {"wifi_throughput": {**NAMED["wifi_throughput"], "products": [{**p, "project_name": "模擬專案"} for p in NAMED["wifi_throughput"]["products"]]}}
    assert stats.with_hints(plan, "模擬專案的吞吐量", same)["products"] == []                       # two devices share the name: it does not settle one


def test_a_choice_that_turned_out_to_have_no_data_is_replaced_not_stacked():
    only_handover = {"cellular_handover": CAT["cellular_handover"]}
    step = stats.next_step({"needed": True, "technology": "wifi", "report_type": None, "products": [], "all_products": False, "metrics": []}, only_handover)
    assert step["ask"]["drop"] == ["（WiFi）"]
    events = []
    st = stats.ReportStats(lambda m: json.dumps({"needed": True, "technology": "wifi", "report_type": None, "products": [], "metrics": [], "filters": {}}), lambda: _source(only_handover))
    result = ZoneAgent(Catalog(), lambda m: "x", stats=st).answer(task_id="t", zone_label="z", zone_names=["z"], question="吞吐量平均是多少？（WiFi）", history=[], owner={}, file_records={},
                                                                 emit=events.append, with_stats=True)
    assert result["extension"]["followups"] == ["吞吐量平均是多少？（5G 換手）"]


def _source(cat):
    from contextlib import contextmanager
    from types import SimpleNamespace

    @contextmanager
    def s():
        yield SimpleNamespace(catalog=lambda: cat, stats=lambda **p: {"rows": [], "truncated": False, "series": [], "group_by": []})
    return s()


def test_an_answer_that_says_nothing_found_but_goes_on_to_the_data_keeps_its_citation_and_scope():
    long_answer = "在這個專區的資料裡找不到 WiFi 的吞吐量；相近內容是換手測試：平均 800 Mbps。[S1]" + "補充說明。" * 20
    result = ask(lambda messages: long_answer)
    assert [c["ref"] for c in result["citations"]] == ["S1"] and result["answer_main"].startswith(f"**依據：{SCOPE}**")
    bare = ask(lambda messages: "在這個專區的資料裡找不到 WiFi 的吞吐量。[S1]")
    assert bare["citations"] == [] and not bare["answer_main"].startswith("**依據")


def test_a_trailing_zero_is_not_a_number_missing_from_the_data():
    from src.zone_pages.agent import grounding
    ok = grounding("平均 454.0 Mbps，最大 1,000.50 Mbps，p95 49.5 [S1]", "平均 454 最大 1000.5 p95 49.5", 1, 1)
    assert ok["flagged"] == [] and ok["summary"]["values_not_found"] == 0
    bad = grounding("平均 455.0 Mbps [S1]", "平均 454", 1, 1)
    assert [f["value"] for f in bad["flagged"]] == ["455.0"]


def test_a_question_about_the_project_gets_the_reports_particulars_even_when_no_numbers_are_wanted():
    info = stats.info_passages("剛剛的數據的案子名稱是甚麼？", NAMED)
    assert len(info) == 1 and info[0]["source"] == "報告基本資料"
    assert "- 案子 第一案（PRJ-001），測試案例 整機測試，任務 吞吐量，設備 PKE3540J，WiFi 吞吐量報告 DOC-A" in info[0]["content"]
    assert "- 案子 第二案（PRJ-002），設備 PKE9999，WiFi 吞吐量報告 DOC-B" in info[0]["content"]
    assert stats.info_passages("平均吞吐量是多少？", NAMED) == [] and stats.info_passages("案子", {}) == []
    no_numbers = stats.ReportStats(lambda m: json.dumps({"needed": False}), lambda: _source(NAMED)).consult("剛剛的數據的案子名稱是甚麼？")
    assert no_numbers["ask"] is None and [p["source"] for p in no_numbers["passages"]] == ["報告基本資料"]
    nothing = stats.ReportStats(lambda m: json.dumps({"needed": False}), lambda: _source(NAMED)).consult("測試目的是什麼？")
    assert nothing["passages"] == []


def test_the_info_follows_the_numbers_when_both_are_asked_for():
    st = stats.ReportStats(lambda m: plan_reply(), lambda: fake_source())
    got = st.consult("PKE3540J 這個案子的 5GHz 80MHz 下行平均吞吐量？")["passages"]
    assert [p["source"].split("（")[0] for p in got] == ["測試數據彙總", "報告基本資料"] and got[0]["scope"]


def test_a_test_case_id_with_a_frequency_a_plus_and_a_case_number_is_accepted():
    from src.report_numeric import stats as rs
    from tests.zone_pages.test_stats import Conn
    ids = ["cellular_throughput:n79@4850:100MHz:DDDSU+UDSUU (4:4)#case4", "cellular_throughput:Band2@None:100MHz:DSUU (2:2)"]
    conn = Conn()
    rs.measurement_stats(conn, "cellular_throughput", filters={"test_cases": ids})
    assert conn.params[-1]["cases"] == ids
    import pytest
    from src.report_numeric.query import QueryError
    with pytest.raises(QueryError):
        rs.measurement_stats(Conn(), "cellular_throughput", filters={"test_cases": ["a'; drop table x; --"]})


def test_cases_with_an_unreadable_frequency_come_last():
    from src.report_numeric import stats as rs
    from tests.zone_pages.test_stats import Conn
    conn = Conn()
    rs.measurement_stats(conn, "cellular_throughput")
    order = conn.sql[-1].split("ORDER BY")[-1]
    assert order.index("m.value_basis") < order.index("(m.center_freq_mhz IS NULL)") < order.index("m.test_case_id")
    handover = Conn()
    rs.measurement_stats(handover, "cellular_handover")
    assert "center_freq_mhz IS NULL" not in handover.sql[-1]


def test_the_report_s_own_average_answers_an_average_question():
    cat = {"cellular_throughput": {**CAT["cellular_handover"], "dims": {"statistic": ["average", "peak", "value"]}}}
    params = {"report_type": "cellular_throughput", "filters": {}}
    assert stats.default_statistic(params, cat, "5G 吞吐量平均是多少？")["filters"] == {"statistic": "average"}
    assert stats.default_statistic(params, cat, "吞吐量的峰值是多少？")["filters"] == {}
    assert stats.default_statistic(params, cat, "平均和最大吞吐量")["filters"] == {}
    assert stats.default_statistic(params, cat, "吞吐量是多少？")["filters"] == {}
    assert stats.default_statistic({"report_type": "cellular_throughput", "filters": {"statistic": "peak"}}, cat, "平均")["filters"] == {"statistic": "peak"}
    one = {"cellular_handover": {**CAT["cellular_handover"], "dims": {"statistic": ["average"]}}}
    assert stats.default_statistic({"report_type": "cellular_handover", "filters": {}}, one, "平均")["filters"] == {}


def test_test_case_4_in_a_question_about_numbers_is_not_a_question_about_the_project():
    assert stats.info_passages("Test Case 4 的下行吞吐量是多少？", NAMED) == []
    assert stats.info_passages("這份報告的測試案例是什麼？", NAMED) and stats.info_passages("which project is it?", NAMED) and stats.info_passages("what case is it", NAMED)
