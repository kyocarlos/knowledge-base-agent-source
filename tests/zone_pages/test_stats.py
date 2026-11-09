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
    group = lambda rt, **kw: (lambda c: (rs.measurement_stats(c, rt, **kw), [q for q in c.sql if "GROUP BY" in q][0].split("GROUP BY")[1].split("ORDER BY")[0])[1])(Conn())
    wifi = group("wifi_throughput")
    assert all(c in wifi for c in ("m.band", "m.bandwidth_mhz", "m.direction", "m.protocol", "m.metric_name", "m.value_basis")) and "m.channel" not in wifi
    assert "m.channel" in group("wifi_throughput", group_by=["channel"])
    rvr = group("wifi_rvr")
    assert "m.attenuation_db" in rvr and "m.angle_deg" in rvr and "m.direction" in rvr
    assert "m.test_case_id" in group("cellular_handover") and "m.band" not in group("cellular_handover")
    cellular = group("cellular_throughput")
    assert all(c in cellular for c in ("m.time_slot", "m.center_freq_mhz", "m.statistic", "m.traffic_mode", "m.protocol", "m.direction", "m.test_case_id"))      # cases that share every condition (a starred case, tested with another UE) are not merged


def test_a_report_type_nobody_described_is_grouped_on_every_condition():
    strict = (lambda c: (rs.measurement_stats(c, "fiber_olt_power"), [q for q in c.sql if "GROUP BY" in q][0].split("GROUP BY")[1].split("ORDER BY")[0])[1])(Conn())
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
    assert "吞吐量 Mbps（依衰減）：30 dB 655.2" in one and "已截斷" in one
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


RVR_CAT = {"wifi_rvr": {"products": [{"id": "CHS3320N", "model": "CHS3320N", "document_id": "SIT-TR-WL-RvR-CHS3320N"}], "metrics": [{"name": "throughput", "unit": "Mbps", "description": None, "numbered": False}],
                        "dims": {"band": ["2.4GHz"], "channel": [1, 6, 11], "center_freq_mhz": [2412, 2437, 2462], "direction": ["dl"]}, "cases": [],
                        "series": ["band", "bandwidth_mhz", "direction", "attenuation_db", "angle_deg"]}}


def rvr_row(channel, freq, attn, value):
    return {"product_id": "CHS3320N", "dut_model": "CHS3320N-D388", "report_type": "wifi_rvr", "document_id": "SIT-TR-WL-RvR-CHS3320N", "metric_name": "throughput", "unit": "Mbps",
            "value_basis": "measured", "test_case_name": "2.4GHz - 20MHz 衰減掃描", "band": "2.4GHz", "bandwidth_mhz": 20, "direction": "dl", "attenuation_db": attn, "channel": channel,
            "center_freq_mhz": freq, "n": 1, "total": value, "average": value, "minimum": value, "maximum": value, "median": value, "p95": value, "first_no": None, "last_no": None}


def test_wifi_channels_are_listed_one_by_one_with_their_frequency_unless_asked_together():
    base = {"report_type": "wifi_rvr", "products": None, "documents": None, "metrics": None, "filters": {}, "group_by": [], "from_no": None, "to_no": None}
    got = stats.default_channels(base, RVR_CAT, "列出 CHS3320N 的 2.4G 所有 Throughput 測試數據")
    assert got["group_by"] == ["channel", "center_freq_mhz"]
    assert stats.default_channels(base, RVR_CAT, "所有通道的平均吞吐量")["group_by"] == []
    assert stats.default_channels({**base, "filters": {"channel": 6}}, RVR_CAT, "通道 6 的吞吐量")["group_by"] == []
    assert stats.default_channels({**base, "report_type": "cellular_handover"}, CAT, "換手")["group_by"] == []
    assert stats.default_channels({**base, "group_by": ["channel"]}, RVR_CAT, "逐通道")["group_by"] == ["channel", "center_freq_mhz"]


def test_an_attenuation_sweep_is_one_line_per_channel_never_a_statistic_over_the_channels():
    rows = [rvr_row(c, f, a, v) for c, f, vals in ((1, 2412, (389.6, 385.0)), (6, 2437, (421.8, 419.9)), (11, 2462, (424.8, 427.7))) for a, v in zip((0.0, 3.0), vals)]
    text = stats.render({"rows": rows, "truncated": False, "series": CAT_SERIES, "group_by": ["channel", "center_freq_mhz"]}, {})
    assert "【CHS3320N-D388／2.4GHz - 20MHz 衰減掃描／2.4GHz，20MHz，下行（報告 Rx），Ch1（2412 MHz）】" in text
    assert "- 吞吐量 Mbps（依衰減）：0 dB 389.6；3 dB 385" in text and "Ch11（2462 MHz）】" in text and "Ch6（2437 MHz）" in text
    assert "平均" not in text.split(chr(10), 1)[1] and "最小" not in text and "n 3" not in text


CAT_SERIES = RVR_CAT["wifi_rvr"]["series"]


def test_a_few_measurements_of_one_condition_are_listed_each_before_the_statistics():
    row = {**WIFI_ROW, "n": 3, "average": 686.6667, "minimum": 680.0, "maximum": 697.0, "median": 683.0, "vals": [680.0, 683.0, 697.0], "nos": [1, 2, 3]}
    text = stats.render({"rows": [row], "truncated": False, "series": CAT["wifi_throughput"]["series"], "group_by": []}, {})
    assert "吞吐量（各次）：#1 680；#2 683；#3 697 Mbps（n 3，平均 686.7，最小 680，最大 697，中位數 683）" in text
    assert "p95 " not in text.split("（各次）")[1]
    many = {**row, "n": 40, "vals": None, "nos": None}
    assert "n 40，平均" in stats.render({"rows": [many], "truncated": False, "series": CAT["wifi_throughput"]["series"], "group_by": []}, {})   # a long series stays statistics only
    assert stats.STATISTIC_ZH["value"] == "各次量測"


def test_the_query_returns_each_value_of_a_small_group():
    from src.report_numeric import stats as rs
    assert rs.EACH_VALUE_UP_TO == 10


def wifi_tput_row(ch, freq, metric, direction, value, band="2.4GHz", bw=20):
    return {"product_id": "CHS3320N", "dut_model": "CHS3320N-D388", "report_type": "wifi_throughput", "document_id": "SIT-TR-WL-Throughput-CHS3320N", "metric_name": metric,
            "unit": "dBm" if metric == "rssi" else "Mbps", "value_basis": "measured", "band": band, "bandwidth_mhz": bw, "direction": direction, "protocol": "tcp" if direction else None,
            "channel": ch, "center_freq_mhz": freq, "n": 1, "total": value, "average": value, "minimum": value, "maximum": value, "median": value, "p95": value, "first_no": None, "last_no": None}


def test_a_wifi_throughput_report_is_one_line_per_channel_with_uplink_downlink_rssi_and_the_verdict():
    rows = [wifi_tput_row(1, 2412, "throughput", "dl", 390.77), wifi_tput_row(1, 2412, "throughput", "ul", 356.75), wifi_tput_row(1, 2412, "rssi", None, -24.63),
            wifi_tput_row(2, 2417, "throughput", "dl", 408.43), wifi_tput_row(2, 2417, "throughput", "ul", 411.98), wifi_tput_row(2, 2417, "rssi", None, -24.75)]
    verdicts = [{"document_id": "SIT-TR-WL-Throughput-CHS3320N", "band": "2.4GHz", "bandwidth_mhz": 20, "channel": 1, "result": "pass", "criteria_value": 344.2, "criteria_unit": "Mbps"}]
    text = stats.render({"rows": rows, "truncated": False, "series": CAT["wifi_throughput"]["series"], "group_by": ["channel", "center_freq_mhz"], "verdicts": verdicts}, {})
    assert "【CHS3320N-D388／2.4GHz，20MHz】" in text
    assert "- Ch1（2412 MHz）：下行 390.77，上行 356.75 Mbps，RSSI -24.63 dBm，判定 Pass（基準 344.2 Mbps）" in text
    assert "- Ch2（2417 MHz）：下行 408.43，上行 411.98 Mbps，RSSI -24.75 dBm" in text and "判定" not in text.split("Ch2")[1]


def test_a_cut_result_says_so_first_and_keeps_whole_lines():
    rows = [wifi_tput_row(i, 2400 + i, "throughput", "dl", 400.0 + i) for i in range(1, 400)]
    text = stats.render({"rows": rows, "truncated": False, "series": CAT["wifi_throughput"]["series"], "group_by": ["channel", "center_freq_mhz"], "verdicts": []}, {})
    assert len(text) <= stats.MAX_CHARS + 400 and text.startswith("【注意】內容太長，已截斷") and "資料不完整" in text.split(chr(10))[0]
    assert text.rstrip().endswith("Mbps")                      # cut at a whole line, not in the middle of a number
    flagged = stats.render({"rows": rows[:3], "truncated": True, "series": CAT["wifi_throughput"]["series"], "group_by": ["channel"]}, {})
    assert flagged.startswith("【注意】查詢結果超過") and "已截斷" in flagged.split(chr(10))[0]


def test_the_verdicts_of_each_channel_are_asked_for_with_the_same_filters():
    conn = Conn()
    rs.measurement_stats(conn, "wifi_throughput", filters={"band": "2.4GHz", "bandwidth_mhz": 20}, group_by=["channel"], documents=["SIT-TR-WL-Throughput-CHS3320N"])
    sql = [q for q in conn.sql if "test_item_result" in q]
    assert len(sql) == 1 and conn.params[conn.sql.index(sql[0])]["band"] == "2.4GHz" and conn.params[conn.sql.index(sql[0])]["docs"] == ["SIT-TR-WL-Throughput-CHS3320N"]
    other = Conn()
    rs.measurement_stats(other, "wifi_throughput")
    assert not [q for q in other.sql if "test_item_result" in q]


def wide_source(rows):
    @contextmanager
    def source():
        yield SimpleNamespace(catalog=lambda: CAT, stats=lambda **p: {"rows": rows, "truncated": False, "series": ["band", "bandwidth_mhz", "direction", "protocol"],
                                                                      "group_by": ["channel", "center_freq_mhz"], "verdicts": []})
    return source


def test_a_result_too_long_for_one_answer_asks_for_a_band_and_bandwidth_or_gives_the_overview():
    rows = [wifi_tput_row(i, 2400 + i, m, d, 400.0 + i, band, bw) for band, bw, n in (("2.4GHz", 20, 11), ("5GHz", 20, 90)) for i in range(1, n + 1)
            for m, d in (("throughput", "dl"), ("throughput", "ul"), ("rssi", None))]
    reply = lambda m: plan_reply()
    got = stats.ReportStats(reply, wide_source(rows)).consult("列出 CHS3320N 的所有 WiFi Throughput 測試數據")
    assert got["passages"] == [] or got["passages"] is not None
    assert got["ask"]["options"] == ["2.4GHz 20MHz", "5GHz 20MHz", "全部頻段（只看摘要）"] and "一次列出太長" in got["ask"]["text"]
    overview = stats.ReportStats(reply, wide_source(rows)).consult("列出 CHS3320N 的所有 WiFi Throughput 測試數據（全部頻段（只看摘要））")
    assert overview["ask"] is None
    text = overview["passages"][0]["content"]
    assert "2.4GHz 20MHz，下行（報告 Rx），吞吐量：11 個數值，最小 401，最大 411，平均 406" in text and "5GHz 20MHz" in text and len(text) < stats.WIDE_RESULT_CHARS
    short = stats.ReportStats(reply, wide_source(rows[:33])).consult("列出 CHS3320N 的 2.4G Throughput 測試數據")
    assert short["ask"] is None and "Ch1（2401 MHz）" in short["passages"][0]["content"]     # one band and bandwidth fits one answer


def test_a_question_for_the_data_is_fetched_even_when_the_planner_says_no_numbers_or_answers_nothing():
    for planner in (lambda m: json.dumps({"needed": False}), lambda m: "抱歉，我無法處理", lambda m: ""):
        got = stats.ReportStats(planner, lambda: fake_source()).consult("列出 PKE3540J 的所有 WiFi Throughput 測試數據")
        assert got["ask"] is None and got["passages"] and "吞吐量" in got["passages"][0]["content"]
        # a question about what a report holds, without asking for the numbers, is still only asked back or answered from the documents
        assert stats.ReportStats(planner, lambda: fake_source()).consult("WiFi Throughput 報告的測試方法是什麼")["passages"] == []
