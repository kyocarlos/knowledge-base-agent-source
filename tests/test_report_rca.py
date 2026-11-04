"""RCA verification: the checker must reject what a careless model would write. No database, no real model."""
import copy,json
import pytest
from src.report_numeric import compare,rca

def run(rid,fw,v36,*,hw="A",extra=None):
    ms=[{"test_case_id":"TP","test_case_name":None,"metric_name":"throughput","value":v36,"unit":"Mbps","value_basis":"measured","band":"5GHz","bandwidth_mhz":80,"channel":36,
         "direction":"dl","attenuation_db":None,"angle_deg":None,"traffic_mode":None,"protocol":None,"statistic":None,"sample_index":None,"wireless_mode":None,"time_slot":None,
         "source_sheet":"Throughput","source_cell_range":"B2"}]
    return {"test_run_id":rid,"product_id":"P","dut_model":"P","report_type":"wifi_throughput","technology":"WiFi7","document_id":"D"+rid,"document_version":"1","report_revision":None,
            "npi_stage":"EVT","firmware_version":fw,"hardware_version":hw,"chipset_vendor":"Q","ethernet_type":None,"test_date":"2026-10-01","overall_result":"pass",
            "quality_status":"clean","formula_error_count":0,"approval_basis":"assumed_manual","measurements":ms,"results":[],"criteria":[],"conditions":[]}

@pytest.fixture
def pack():
    return compare.compare_runs([run("A","1.0.0",900),run("B","1.1.0",650)])
@pytest.fixture
def confounded():
    return compare.compare_runs([run("A","1.0.0",900),run("B","1.1.0",650,hw="B")])

def ids(p):
    return {"f":next(f["id"] for f in p["factors"] if f["factor"]=="firmware_version"),"d":p["diffs"][0]["id"]}
def good(p):
    i=ids(p)
    return {"summary":"韌體由 1.0.0 變為 1.1.0，5GHz 80MHz ch36 下行吞吐量由 900 Mbps 變為 650 Mbps。",
            "observations":[{"text":"ch36 下行 900 Mbps → 650 Mbps，差 -250 Mbps。","evidence":[i["d"]]},{"text":"韌體版本不同。","evidence":[i["f"]]}],
            "hypotheses":[{"cause":"新韌體對 5GHz ch36 的資料路徑有改動","mechanism":"同一硬體、同一條件下只有韌體不同，數值下降","supports":[i["f"],i["d"]],"against":[],
                           "missing_evidence":["韌體 1.1.0 的釋出說明"],"confidence":"high","verify_steps":["以 1.0.0 韌體在同一環境重測 ch36"]}],
            "unexplained":[],"data_gaps":["只有兩份報告，尚未排除環境差異"]}

def test_a_grounded_analysis_passes_and_high_needs_both_factor_and_measurement(pack):
    r=rca.verify(good(pack),pack)
    assert r["ok"],r["violations"]
    assert r["analysis"]["hypotheses"][0]["confidence"]=="high" and not r["warnings"]

def test_unknown_evidence_ids_and_uncited_claims_are_rejected(pack):
    a=good(pack);a["observations"][0]["evidence"]=["D99"]
    assert any("D99" in v for v in rca.verify(a,pack)["violations"])
    a=good(pack);a["observations"][1]["evidence"]=[]
    assert any("沒有引用" in v for v in rca.verify(a,pack)["violations"])

def test_numbers_outside_the_evidence_are_rejected(pack):
    a=good(pack);a["summary"]="吞吐量下降了約 37%，由 900 降到 650。"
    r=rca.verify(a,pack);assert not r["ok"] and any("37" in v for v in r["violations"])
    a=good(pack);a["summary"]="由 900 Mbps 降到 650 Mbps，下降 27.8%。"      # a rounding of the code-computed delta_pct is allowed
    assert rca.verify(a,pack)["ok"]

def test_direction_words_are_banned_until_the_direction_is_defined(pack):
    a=good(pack);a["summary"]="吞吐量明顯變差。"
    assert any("尚未定義" in v for v in rca.verify(a,pack)["violations"])

def test_confounded_runs_cap_confidence_and_require_a_plan_to_separate_factors(confounded):
    assert confounded["confounded"]
    a=good(confounded);r=rca.verify(a,confounded)
    assert not r["ok"] and any("拆開變因" in v for v in r["violations"])
    a["data_gaps"]=["韌體與硬體同時變動，需要只換一個變因重測"]
    r=rca.verify(a,confounded);assert r["ok"] and r["analysis"]["hypotheses"][0]["confidence"]=="medium" and r["warnings"]

def test_high_confidence_without_a_factor_is_downgraded(pack):
    a=good(pack);a["hypotheses"][0]["supports"]=[ids(pack)["d"]]
    r=rca.verify(a,pack);assert r["ok"] and r["analysis"]["hypotheses"][0]["confidence"]=="medium" and r["warnings"]

def test_hypotheses_need_verification_steps_and_a_valid_confidence(pack):
    a=good(pack);a["hypotheses"][0]["verify_steps"]=[]
    assert any("驗證步驟" in v for v in rca.verify(a,pack)["violations"])
    a=good(pack);a["hypotheses"][0]["confidence"]="certain"
    assert any("confidence" in v for v in rca.verify(a,pack)["violations"])

def test_run_rca_gives_the_model_one_correction_round_then_rejects(pack):
    calls=[]
    bad=good(pack);bad["summary"]="下降 99%"
    def llm(messages):
        calls.append(messages);return json.dumps(bad if len(calls)==1 else good(pack),ensure_ascii=False)
    out=rca.run_rca(pack,llm)
    assert out["status"]=="ok" and out["attempts"]==2 and "99" in calls[1][-1]["content"]
    out=rca.run_rca(pack,lambda m:"not json at all")
    assert out["status"]=="rejected" and out["analysis"] is None and out["attempts"]==2

def test_prompt_carries_the_evidence_ids_but_not_raw_rows(pack):
    msgs=[]
    rca.run_rca(pack,lambda m:msgs.append(m) or "{}",retries=0)
    user=msgs[0][1]["content"]
    assert ids(pack)["d"] in user and "source_cell_range" not in user and "規則" not in user
    assert "higher_is_better" in rca.SYSTEM_PROMPT
