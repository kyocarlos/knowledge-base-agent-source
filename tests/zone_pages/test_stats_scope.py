"""An answer built from the database's numbers says first which kind of report, device and document they come from."""
import json

from src.zone_pages import stats
from src.zone_pages.agent import ZoneAgent
from tests.zone_pages.test_stats import CAT, Catalog, WIFI_ROW, XN_ROW, fake_source, plan_reply

SCOPE = "WiFi 吞吐量報告 SIT-TR-WL-Throughput-PKE3540J（設備 PKE3540J）"


def ask(complete, rows=None):
    st = stats.ReportStats(lambda m: plan_reply(), lambda: fake_source(rows=rows))
    return ZoneAgent(Catalog(), complete, stats=st).answer(task_id="t", zone_label="產品驗證專區", zone_names=["產品驗證專區"], question="5GHz 80MHz 下行平均吞吐量？", history=[], owner={},
                                                           file_records={}, emit=lambda e: None, with_stats=True)


def test_the_passage_names_the_report_type_the_device_and_the_document():
    got = stats.ReportStats(lambda m: plan_reply(), lambda: fake_source()).consult("?")["passages"][0]
    assert got["scope"] == SCOPE and got["content"].startswith(f"資料來源：{SCOPE}\n")
    two = stats.ReportStats(lambda m: plan_reply(), lambda: fake_source(rows=[WIFI_ROW, XN_ROW])).consult("?")["passages"][0]
    assert two["scope"] == SCOPE + "；5G 換手報告 SIT-SR-SC-NR-Handover-SCU2050（設備 SCU2050）"


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
