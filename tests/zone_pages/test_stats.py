"""Test-report numbers in the zone's answers: what the database holds is shown to the model, the plan is checked against it, the database computes."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from src.report_numeric import query as q
from src.report_numeric import stats as rs
from src.zone_pages import stats
from src.zone_pages.agent import ZoneAgent

CAT = {
    "wifi_throughput": {"products": [{"id": "PKE3540J", "model": "PKE3540J", "document_id": "SIT-TR-WL-Throughput-PKE3540J"}],
                        "metrics": [{"name": "throughput", "unit": "Mbps", "description": None, "numbered": False}, {"name": "rssi", "unit": "dBm", "description": None, "numbered": False}],
                        "dims": {"band": ["2.4GHz", "5GHz"], "bandwidth_mhz": [20, 40, 80], "direction": ["dl", "ul"], "channel": [1, 6, 36], "protocol": ["tcp"]}, "cases": [],
                        "series": ["band", "bandwidth_mhz", "direction", "protocol"]},
    "cellular_handover": {"products": [{"id": "SCU2050", "model": "SCU2050", "document_id": "SIT-SR-SC-NR-Handover-SCU2050"}],
                          "metrics": [{"name": "latency_rtt_after_ho", "unit": "ms", "description": None, "numbered": True}, {"name": "ho_success", "unit": "count", "description": None, "numbered": True}],
                          "dims": {"band": ["n77"]}, "cases": [{"id": "cellular_handover:xn:100", "name": "Xn Handover 100 times"}, {"id": "cellular_handover:ng:100", "name": "NG Handover 100 times"}],
                          "series": ["test_case_id"]},
}
WIFI_ROW = {"product_id": "PKE3540J", "dut_model": "PKE3540J", "report_type": "wifi_throughput", "document_id": "SIT-TR-WL-Throughput-PKE3540J", "metric_name": "throughput", "unit": "Mbps",
            "value_basis": "measured", "band": "5GHz", "bandwidth_mhz": 80, "direction": "dl", "protocol": "tcp", "n": 3, "total": 2400.0, "average": 800.0, "minimum": 790.0,
            "maximum": 812.0, "median": 798.0, "p95": 810.0, "first_no": None, "last_no": None}
XN_ROW = {"product_id": "SCU2050", "dut_model": "SCU2050", "report_type": "cellular_handover", "document_id": "SIT-SR-SC-NR-Handover-SCU2050", "metric_name": "latency_rtt_after_ho",
          "unit": "ms", "value_basis": "measured", "test_case_id": "cellular_handover:xn:100", "test_case_name": "Xn Handover 100 times", "n": 21, "total": 700.0, "average": 33.3333,
          "minimum": 26.0, "maximum": 49.0, "median": 31.0, "p95": 45.0, "first_no": 40, "last_no": 60}


class Conn:
    """Records the SQL and parameters a query sends and answers with the given rows."""

    def __init__(self, rows=None):
        self.rows, self.sql, self.params = rows or [], [], []

    def execute(self, sql, params=None):
        self.sql.append(sql)
        self.params.append(params)
        cols = list(self.rows[0]) if self.rows else ["x"]
        return SimpleNamespace(description=[SimpleNamespace(name=c) for c in cols], fetchall=lambda: [tuple(r.values()) for r in self.rows])


def test_each_report_type_always_separates_the_conditions_that_must_not_be_averaged():
    group = lambda rt, **kw: (lambda c: (rs.measurement_stats(c, rt, **kw), c.sql[-1].split("GROUP BY")[1].split("ORDER BY")[0])[1])(Conn())
    wifi = group("wifi_throughput")
    assert all(c in wifi for c in ("m.band", "m.bandwidth_mhz", "m.direction", "m.protocol", "m.metric_name", "m.value_basis")) and "m.channel" not in wifi
    assert "m.channel" in group("wifi_throughput", group_by=["channel"])
    rvr = group("wifi_rvr")
    assert "m.attenuation_db" in rvr and "m.angle_deg" in rvr and "m.direction" in rvr
    assert "m.test_case_id" in group("cellular_handover") and "m.band" not in group("cellular_handover")
    cellular = group("cellular_throughput")
    assert all(c in cellular for c in ("m.time_slot", "m.center_freq_mhz", "m.statistic", "m.traffic_mode", "m.protocol", "m.direction", "m.test_case_id"))      # cases that share every condition (a starred case, tested with another UE) are not merged


def test_a_report_type_nobody_described_is_grouped_on_every_condition():
    strict = (lambda c: (rs.measurement_stats(c, "fiber_olt_power"), c.sql[-1].split("GROUP BY")[1].split("ORDER BY")[0])[1])(Conn())
    assert all(f"m.{d}" in strict for d in ("test_case_id", *rs.CONDITIONS))
    assert rs.optional_dims("fiber_olt_power") == []


def test_values_are_bound_never_written_into_the_sql():
    c = Conn()
    rs.measurement_stats(c, "wifi_throughput", metrics=["throughput"], filters={"band": "5GHz", "bandwidth_mhz": 80, "direction": "dl", "test_cases": ["a:b"]}, from_no=3, to_no=9)
    sql, params = c.sql[-1], c.params[-1]
    assert "5GHz" not in sql and "throughput'" not in sql and "%(band)s" in sql
    assert params["band"] == "5GHz" and params["bandwidth_mhz"] == 80 and params["metrics"] == ["throughput"] and params["lo"] == 3 and params["hi"] == 9 and params["rt"] == "wifi_throughput"


def test_the_query_refuses_what_is_not_on_its_lists():
    for bad in ({"report_type": "x; drop table km_test.test_run"}, {"report_type": "wifi_rvr", "metrics": ["a b"]}, {"report_type": "wifi_rvr", "filters": {"band": "7GHz"}},
                {"report_type": "wifi_rvr", "filters": {"direction": "sideways"}}, {"report_type": "wifi_rvr", "filters": {"sql": "1"}}, {"report_type": "wifi_rvr", "group_by": ["band"]},
                {"report_type": "wifi_rvr", "from_no": 0}, {"report_type": "wifi_rvr", "products": ["a"] * 6}, {"report_type": "wifi_rvr", "filters": {"test_cases": ["a'; --"]}},
                {"report_type": "wifi_rvr", "filters": {"attenuation_db": 99999}}):
        with pytest.raises(q.QueryError):
            rs.measurement_stats(Conn(), **bad)


def test_the_catalog_lists_what_the_database_holds():
    class Cat(Conn):
        def execute(self, sql, params=None):
            self.sql.append(sql)
            if "FROM km_test.test_run r WHERE" in sql:
                rows = [{"report_type": "wifi_throughput", "product_id": "P1", "dut_model": "P1", "document_id": "D1", "project_id": "PRJ-1", "project_name": "案子一", "case_name": None,
                         "task_name": None}]
            elif "metric_dictionary md" in sql:
                rows = [{"report_type": "wifi_throughput", "metric_name": "throughput", "unit": "Mbps", "description": "d", "band": ["5GHz"], "bandwidth_mhz": [80], "channel": None,
                         "direction": ["dl"], "attenuation_db": None, "angle_deg": None, "traffic_mode": None, "protocol": ["tcp"], "statistic": None, "first_no": None, "last_no": None}]
            else:
                rows = [{"report_type": "wifi_throughput", "test_case_id": "t1", "name": "n"}]
            return SimpleNamespace(description=[SimpleNamespace(name=c) for c in rows[0]], fetchall=lambda: [tuple(r.values()) for r in rows])
    cat = rs.catalog(Cat())
    assert cat["wifi_throughput"]["products"][0]["id"] == "P1" and cat["wifi_throughput"]["dims"] == {"band": ["5GHz"], "bandwidth_mhz": [80], "direction": ["dl"], "protocol": ["tcp"]}
    assert cat["wifi_throughput"]["metrics"][0]["unit"] == "Mbps" and cat["wifi_throughput"]["cases"] == []     # test cases only where they carry a condition
    assert rs.catalog(Conn()) == {}


def test_the_model_is_shown_the_catalog_and_the_plan_is_held_to_it():
    text = stats.describe(CAT)
    assert "wifi_rvr" not in text and "PKE3540J" in text and "bandwidth_mhz：20, 40, 80" in text and "cellular_handover:xn:100（Xn Handover 100 times）" in text
    assert "不會被平均在一起的條件：band、bandwidth_mhz、direction、protocol" in text
    plan = {"needed": True, "report_type": "wifi_throughput", "products": ["PKE3540J", " "], "metrics": ["throughput", "bogus"], "group_by": ["channel", "band", "x"],
            "filters": {"band": "5ghz", "bandwidth_mhz": 160, "direction": "dl", "test_cases": ["nope"], "sql": "1", "attenuation_db": 30}, "from_no": 99999}
    p = stats.to_query(plan, CAT)
    assert p["metrics"] == ["throughput"] and p["group_by"] == ["channel"] and p["from_no"] is None and p["products"] == ["PKE3540J"]
    assert p["filters"] == {"band": "5GHz", "direction": "dl", "attenuation_db": 30}      # 160 MHz is not in the data, "sql" is not a condition, "nope" is not a test case
    assert stats.to_query({"needed": True, "report_type": "not_a_type"}, CAT) is None
    h = stats.to_query({"needed": True, "report_type": "cellular_handover", "filters": {"test_cases": ["cellular_handover:xn:100", "zzz"]}, "from_no": 40, "to_no": 60}, CAT)
    assert h["filters"] == {"test_cases": ["cellular_handover:xn:100"]} and (h["from_no"], h["to_no"]) == (40, 60)


def test_only_a_plan_that_asks_for_numbers_is_used():
    assert stats.parse_plan(json.dumps({"needed": True, "report_type": "x"}))["report_type"] == "x"
    assert stats.parse_plan('```json\n{"needed": true}\n```') is not None
    assert stats.parse_plan(json.dumps({"needed": False})) is None and stats.parse_plan("not json") is None and stats.parse_plan("") is None


def test_the_result_is_text_the_answer_can_quote():
    wifi = stats.render({"rows": [WIFI_ROW], "truncated": False, "series": CAT["wifi_throughput"]["series"], "group_by": []}, {})
    assert "【PKE3540J／5GHz，80MHz，下行（報告 Rx），TCP】" in wifi and "吞吐量：n 3，平均 800 Mbps，最小 790，最大 812，中位數 798，p95 810" in wifi
    one = stats.render({"rows": [{**WIFI_ROW, "n": 1, "average": 655.2, "attenuation_db": 30.0}], "truncated": True, "series": ["band", "attenuation_db"], "group_by": []}, {})
    assert "吞吐量：655.2 Mbps" in one and "已截斷" in one
    ho = stats.render({"rows": [XN_ROW, {**XN_ROW, "metric_name": "ho_success", "unit": "count", "total": 20.0}], "truncated": False, "series": ["test_case_id"], "group_by": []}, {"from_no": 40, "to_no": 60})
    assert "只計第 40～60 次" in ho and "【SCU2050／Xn Handover 100 times】" in ho and "換手後延遲：n 21，平均 33.33 ms" in ho and "換手成功 20／21 次" in ho


@contextmanager
def fake_source(cat=CAT, rows=None, boom=False):
    seen = []

    def run(**p):
        seen.append(p)
        if boom:
            raise q.QueryError("沒有這個設備")
        return {"rows": rows if rows is not None else [WIFI_ROW], "truncated": False, "series": ["band", "bandwidth_mhz", "direction", "protocol"], "group_by": []}
    yield SimpleNamespace(catalog=lambda: cat, stats=run, seen=seen)


def plan_reply(**kw):
    return json.dumps({"needed": True, "report_type": "wifi_throughput", "products": [], "metrics": [], "filters": {}, "group_by": [], "from_no": None, "to_no": None, **kw})


def test_a_failure_adds_nothing_and_no_match_is_said_plainly():
    ask = lambda **kw: stats.ReportStats(lambda m: plan_reply(), lambda: fake_source(**kw)).consult("5GHz 80MHz 下行平均？")["passages"]
    assert ask()[0]["publisher"] == "資料庫彙總" and ask()[0]["limit"] == stats.MAX_CHARS
    assert "沒有符合此查詢的數據" in ask(rows=[])[0]["content"]
    assert ask(boom=True) == [] and ask(cat={}) == []
    assert stats.ReportStats(lambda m: json.dumps({"needed": False}), lambda: fake_source()).consult("目的是什麼")["passages"] == []
    assert stats.ReportStats(lambda m: plan_reply(report_type="zzz"), lambda: fake_source()).consult("?")["passages"] == []

    def broken():
        raise RuntimeError("database down")
    assert stats.ReportStats(lambda m: plan_reply(), broken).consult("?")["passages"] == []


class Catalog:
    def search(self, query, names, top_k=8, include_history=False):
        return [{"doc": {"title": "報告", "revision_id": "r:1", "publisher": "測試報告（CSIT）", "analysis_eligible": True}, "chunk": {"location_label": "4.1", "content": "第 1 次：延遲 30→28 ms"}}]


def ask_agent(complete, with_stats, st):
    events = []
    result = ZoneAgent(Catalog(), complete, stats=st).answer(task_id="t", zone_label="產品驗證專區", zone_names=["產品驗證專區"], question="5GHz 80MHz 下行平均吞吐量？", history=[], owner={},
                                                             file_records={}, emit=events.append, with_stats=with_stats)
    return result, events


def test_the_computed_numbers_come_first_are_not_cut_short_and_are_cited_like_any_passage():
    seen = []

    def complete(messages):
        seen.append(messages)
        return "平均 800 Mbps [S1]。"

    long_rows = [{**WIFI_ROW, "channel": c} for c in range(60)]
    st = stats.ReportStats(lambda m: plan_reply(), lambda: fake_source(rows=long_rows))
    result, events = ask_agent(complete, True, st)
    user = seen[0][-1]["content"]
    assert "[S1] 測試數據彙總" in user and "[S2] 報告" in user and user.count("【PKE3540J") >= 1
    assert len(stats.render({"rows": long_rows, "truncated": False, "series": ["band"], "group_by": ["channel"]}, {})) > 700     # longer than an ordinary passage may be
    assert result["citations"][0]["source"].startswith("測試數據彙總") and result["grounding"]["summary"]["values_not_found"] == 0
    assert {"tool": "query_test_data"} in result["trace"] and any(e.get("label") == "查詢測試數據" for e in events)


def test_a_zone_without_report_numbers_never_asks():
    calls = []
    st = stats.ReportStats(lambda m: calls.append(m) or plan_reply(), lambda: fake_source())
    result, _ = ask_agent(lambda messages: "沒有。", False, st)
    assert calls == [] and {"tool": "query_test_data"} not in result["trace"]
