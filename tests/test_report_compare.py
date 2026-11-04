"""Deterministic report comparison (RCA evidence base) against a real PostgreSQL km_test schema."""
import os,uuid
import psycopg,pytest
from src.report_numeric import compare,timescale

pytestmark=pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),reason="TEST_DATABASE_URL not set")
ROLES=["CSIT_ENGINEER"]

@pytest.fixture
def conn():
    c=psycopg.connect(os.environ["TEST_DATABASE_URL"],autocommit=True)
    c.execute("DROP SCHEMA IF EXISTS km_test CASCADE")
    c.execute(timescale.ddl())
    for m in timescale.load_dictionary():
        c.execute("INSERT INTO km_test.metric_dictionary(metric_name,unit,kind,description) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                  (m["metric_name"],m["unit"],m["kind"],m.get("description")))
    yield c
    c.execute("DROP SCHEMA IF EXISTS km_test CASCADE");c.close()

def add_run(c,rid,*,fw="1.0.0",hw="A",chip="Qualcomm",date="2026-10-01",quality="clean",rtype="wifi_throughput",model="RTF7907VW-D223"):
    c.execute("""INSERT INTO km_test.test_run(test_run_id,id_basis,report_id,document_id,document_version,report_type,technology,product_id,product_id_basis,dut_model,
        npi_stage,firmware_version,hardware_version,chipset_vendor,test_date,overall_result,source_system,approval_status,approval_basis,publish_status,visibility,
        access_roles,access_departments,quality_status,formula_error_count,package_id,schema_version,content_hash)
        VALUES(%s,'derived',%s,%s,'1',%s,'WiFi7',%s,'derived',%s,'EVT',%s,%s,%s,%s,'pass','ManualUpload','approved','assumed_manual','published','internal',
        %s,%s,%s,%s,%s,'1',%s)""",(rid,rid,"DOC-"+rid,rtype,model,model,fw,hw,chip,date,ROLES,["CSIT"],quality,0 if quality=="clean" else 2,"pkg-"+rid,rid))
def add_m(c,rid,case,value,*,metric="throughput",unit="Mbps",band="5GHz",bw=80,ch=36,direction="dl",cell="B2"):
    c.execute("""INSERT INTO km_test.test_measurement(measurement_id,test_run_id,test_case_id,metric_name,value,unit,value_basis,band,bandwidth_mhz,channel,direction,
        source_sheet,source_cell_range) VALUES(%s,%s,%s,%s,%s,%s,'measured',%s,%s,%s,%s,'Throughput',%s)""",(uuid.uuid4(),rid,case,metric,value,unit,band,bw,ch,direction,cell))
def add_r(c,rid,case,label,result):
    c.execute("INSERT INTO km_test.test_item_result(result_id,test_run_id,test_case_id,item_label,result,result_basis,source_sheet,source_cell_range) VALUES(%s,%s,%s,%s,%s,'report','Summary','C3')",
              (uuid.uuid4(),rid,case,label,result))
def add_c(c,rid,name,value):
    c.execute("INSERT INTO km_test.test_condition(condition_id,test_run_id,name,value,source_sheet,source_cell_range) VALUES(%s,%s,%s,%s,'Setup','B7')",(uuid.uuid4(),rid,name,value))

@pytest.fixture
def seeded(conn):
    add_run(conn,"A");add_run(conn,"B",fw="1.1.0",date="2026-10-20");add_run(conn,"C",fw="1.1.0",hw="B",quality="source_errors_accepted")
    for rid,(v36,v40,v44) in {"A":(900,880,870),"B":(650,885,None),"C":(640,880,None)}.items():
        add_m(conn,rid,"TP",v36,ch=36,cell="B2");add_m(conn,rid,"TP",v40,ch=40,cell="B3")
        if v44:add_m(conn,rid,"TP",v44,ch=44,cell="B4")
        add_m(conn,rid,"TP",-55 if rid=="A" else -63,metric="rssi",unit="dBm",ch=36,cell="D2")
    add_r(conn,"A","TP","5GHz 80MHz ch36","pass");add_r(conn,"B","TP","5GHz 80MHz ch36","fail");add_r(conn,"C","TP","5GHz 80MHz ch36","fail")
    add_c(conn,"A","best_angle",90);add_c(conn,"B","best_angle",120);add_c(conn,"C","best_angle",120)
    return conn

def pack(c,ids,**kw):
    return compare.compare_runs(compare.load_runs(c,ids,ROLES),compare.load_directions(c),**kw)

def test_two_runs_find_the_drop_the_factors_and_the_result_change(seeded):
    p=pack(seeded,["A","B"])
    d=next(x for x in p["diffs"] if "ch36" in x["label"] and x["metric"]=="throughput")
    assert d["per_run"][1]["delta"]==-250 and round(d["per_run"][1]["delta_pct"],1)==-27.8 and d["per_run"][1]["source"]=="Throughput!B2"
    assert not any("ch40" in x["label"] and x["metric"]=="throughput" for x in p["diffs"])   # +0.6% is below the 5% default
    assert {f["factor"] for f in p["factors"]}=={"firmware_version","test_date","document_version"} or {"firmware_version","test_date"}<= {f["factor"] for f in p["factors"]}
    assert any(f["factor"]=="條件 best_angle" and f["values"]==[90.0,120.0] for f in p["factors"])
    assert p["result_changes"][0]["outcomes"]==["pass","fail"]
    assert p["coverage"] and "ch44" in p["coverage"][0]["label"]   # only the baseline measured channel 44
    assert p["confounded"] is False

def test_direction_is_not_judged_until_it_is_defined(seeded):
    assert all(x["worst_assessment"]=="changed" for x in pack(seeded,["A","B"])["diffs"])
    seeded.execute("UPDATE km_test.metric_dictionary SET higher_is_better=true WHERE metric_name IN ('throughput','rssi')")
    p=pack(seeded,["A","B"])
    assert next(x for x in p["diffs"] if x["metric"]=="throughput")["worst_assessment"]=="regression"
    assert next(x for x in p["diffs"] if x["metric"]=="rssi")["per_run"][1]["assessment"]=="regression"   # -55 -> -63 dBm

def test_three_runs_flag_confounded_factors_and_quality(seeded):
    p=pack(seeded,["A","B","C"])
    assert p["confounded"] is True and "無法把差異歸因" in p["confounded_note"]
    assert any(q["run"]==2 and q["status"]=="source_errors_accepted" for q in p["quality"])
    d=next(x for x in p["diffs"] if x["metric"]=="throughput" and "ch36" in x["label"])
    assert [r["value"] for r in d["per_run"]]==[900,650,640]

def test_every_number_in_the_pack_traces_to_an_evidence_id(seeded):
    p=pack(seeded,["A","B"])
    assert all(x["id"] in p["evidence"] for x in p["diffs"]+p["coverage"]+p["result_changes"]+p["factors"])
    assert all(p["evidence"][x["id"]]["kind"] in ("measurement","coverage","unit_mismatch","result","factor","condition") for x in p["diffs"]+p["coverage"]+p["result_changes"]+p["factors"])

def test_selection_errors_are_explicit(seeded):
    with pytest.raises(compare.CompareError):compare.load_runs(seeded,["A"],ROLES)
    with pytest.raises(compare.CompareError):compare.load_runs(seeded,["A","NOPE"],ROLES)
    with pytest.raises(compare.CompareError):compare.load_runs(seeded,["A","B"],["SOMEONE_ELSE"])   # not permitted looks the same as missing
    add_run(seeded,"R",rtype="wifi_rvr")
    with pytest.raises(compare.CompareError):compare.compare_runs(compare.load_runs(seeded,["A","R"],ROLES))   # different experiments

def test_identical_runs_have_no_notable_differences(conn):
    add_run(conn,"X");add_run(conn,"Y",date="2026-10-02")
    for rid in ("X","Y"):add_m(conn,rid,"TP",900)
    p=pack(conn,["X","Y"])
    assert p["diffs"]==[] and p["counts"]["unchanged"]==1

def test_thresholds_are_configurable(seeded):
    loose=pack(seeded,["A","B"],thresholds=compare.Thresholds(pct=50.0,per_metric={}))
    assert not any(x["metric"]=="throughput" for x in loose["diffs"])
