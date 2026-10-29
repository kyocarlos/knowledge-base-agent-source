"""CSIT test-report workbooks routed through the registered report templates (src/report_numeric)."""
import os
from pathlib import Path
import pytest
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.pipeline import Pipeline
from src.csit_integration_v1.report_adapter import ReportAdapter,CSIT_POLICY,REPORT_PARSER_VERSION
from src.report_numeric.parser import classify_or_none

SAMPLES=os.getenv("WIFI_REPORT_SAMPLES")  # folder with the Wi-Fi sample reports (kept out of the repo)
JOB={"file_name":"SIT-TR-WL-Throughput-NCQ2200B2V-D294-DV-V10.xlsx","request_payload":{
    "documentId":"11111111-1111-4111-8111-111111111111","version":3,"project":{"id":"p","number":"PRJ-1"}}}

@pytest.mark.parametrize("name,kind",[
 ("SIT-TR-WL-Throughput-X-D1-DV-V10.xlsx","wifi_throughput"),("SIT-TR-WL-RvR-X-D1-DV-V10.xlsx","wifi_rvr"),
 ("SIT-TR-SC-NR-Throughput-SCU5050-n78L-EV-V001.xlsx","cellular_throughput"),
 ("SIT-TR-SC-NR-Thermal-SCU2000-n79-EV-V6.20.xlsx",None),("type2_wifi_SIT-TR-WL-Throughput-X.xlsx",None),("notes.xlsx",None)])
def test_registry_only_knows_registered_templates(name,kind):
    assert classify_or_none(name)==kind

def test_adapter_matches_only_registered_workbooks():
    a=ReportAdapter(None,None,None)
    assert a.matches(JOB)
    assert not a.matches({**JOB,"file_name":"SIT-TR-WL-Throughput-X.pdf"})
    assert not a.matches({**JOB,"file_name":"SIT-TR-SC-NR-Thermal-X.xlsx"})

def test_csit_policy_marks_csit_as_approval_source():
    assert CSIT_POLICY["source_system"]=="CSIT" and CSIT_POLICY["approval_basis"]=="csit"

class FakeRepo:
    def __init__(self,done=()):self.done={p:{"resumed":True} for p in done};self.phases=[];self.finished=None
    def phase(self,job,phase):self.phases.append(phase)
    def checkpoints(self,job):return dict(self.done)
    def checkpoint(self,job,phase,result):self.done[phase]=result
    def finish(self,job,refs,parser,extraction):self.finished=(refs,parser,extraction)
class FakeReports:
    def __init__(self,fail=None):self.calls=[];self.fail=fail
    def parse(self,path,job):return {"package":1}
    def _w(self,name):
        def write(pkg):
            self.calls.append(name)
            if self.fail==name:raise RuntimeError("down")
            return {"wrote":name}
        return write
    write_numeric=property(lambda s:s._w("numeric"));write_graph=property(lambda s:s._w("graph"));write_vectors=property(lambda s:s._w("vectors"))
def pipeline(repo,reports):
    p=Pipeline.__new__(Pipeline);p.repo=repo;p.reports=reports;return p

def test_run_report_writes_three_stores_in_order_and_finishes():
    repo,reports=FakeRepo(),FakeReports()
    pipeline(repo,reports).run_report(JOB,Path("x.xlsx"))
    assert repo.phases==["Parsing","TimescaleDB","Neo4j","Qdrant"] and reports.calls==["numeric","graph","vectors"]
    refs,parser,_=repo.finished
    assert set(refs)=={"TimescaleDB","Neo4j","Qdrant"} and parser==REPORT_PARSER_VERSION

def test_run_report_resumes_after_checkpoint():
    repo,reports=FakeRepo(done=("TimescaleDB","Neo4j")),FakeReports()
    pipeline(repo,reports).run_report(JOB,Path("x.xlsx"))
    assert reports.calls==["vectors"] and repo.finished[0]["TimescaleDB"]=={"resumed":True}

def test_store_outage_is_retryable_and_keeps_earlier_checkpoints():
    repo,reports=FakeRepo(),FakeReports(fail="graph")
    with pytest.raises(IntegrationError) as e:pipeline(repo,reports).run_report(JOB,Path("x.xlsx"))
    assert e.value.retryable and e.value.code=="STORAGE_UNAVAILABLE"
    assert "TimescaleDB" in repo.done and "Neo4j" not in repo.done and repo.finished is None

@pytest.mark.skipif(not SAMPLES,reason="set WIFI_REPORT_SAMPLES to the Wi-Fi sample report folder")
def test_real_wifi_report_gets_csit_identity():
    path=Path(SAMPLES)/JOB["file_name"]
    pkg=ReportAdapter(None,None,None).parse(path,{**JOB,"file_name":path.name})
    run=pkg["test_run"]
    assert pkg["document"]["report_type"]=="wifi_throughput" and pkg["document"]["category"]=="wifi"
    assert (run["id_basis"],run["csit_id"],run["source_record_id"],run["project_id"])==("csit",JOB["request_payload"]["documentId"],JOB["request_payload"]["documentId"]+":v3","PRJ-1")
    assert pkg["policy"]["source_system"]=="CSIT" and pkg["measurements"] and pkg["results"] and pkg["criteria"]
    assert pkg["quality"]["formula_errors"]   # Concurrent sheets hold #REF! cells: reported, never stored as numbers
    assert all(isinstance(m["value"],float) for m in pkg["measurements"])

class _Cur:
    def __init__(self,log):self.log=log
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def executemany(self,sql,rows):self.log.append((sql,list(rows)))
class _Res:
    def __init__(self,row=None,rows=()):self.row,self.rows=row,list(rows)
    def fetchone(self):return self.row
    def fetchall(self):return self.rows
class _Tx:
    def __enter__(self):return self
    def __exit__(self,*a):return False
class FakeConn:
    def __init__(self,existing=None):self.log=[];self.cur_log=[];self.existing=existing
    def transaction(self):return _Tx()
    def cursor(self):return _Cur(self.cur_log)
    def execute(self,sql,params=None):
        self.log.append((" ".join(sql.split()),params))
        if "SELECT content_hash, csit_id" in sql:return _Res(self.existing)
        if "SELECT metric_name, unit FROM km_test.metric_dictionary" in sql:
            from src.report_numeric import timescale
            return _Res(rows=[(m["metric_name"],m["unit"]) for m in timescale.load_dictionary()])
        return _Res()

@pytest.mark.skipif(not SAMPLES,reason="set WIFI_REPORT_SAMPLES to the Wi-Fi sample report folder")
def test_numeric_insert_binds_every_placeholder_with_csit_values():
    import re
    from src.report_numeric import timescale
    path=Path(SAMPLES)/JOB["file_name"]
    pkg=ReportAdapter(None,None,None).parse(path,{**JOB,"file_name":path.name})
    conn=FakeConn();out=timescale.write_package(conn,pkg,accept_source_errors=True)
    assert out["status"]=="written"
    sql,params=next((s,p) for s,p in conn.log if s.startswith("INSERT INTO km_test.test_run "))
    assert set(re.findall(r"%\((\w+)\)s",sql))<=set(params)          # psycopg would raise KeyError otherwise
    assert (params["source_system"],params["approval_basis"],params["id_basis"])==("CSIT","csit","csit")
    assert params["csit_id"]==JOB["request_payload"]["documentId"] and params["quality_status"]=="source_errors_accepted"

@pytest.mark.skipif(not SAMPLES,reason="set WIFI_REPORT_SAMPLES to the Wi-Fi sample report folder")
def test_same_csit_document_replaces_but_other_document_conflicts():
    from src.report_numeric import timescale
    path=Path(SAMPLES)/JOB["file_name"]
    pkg=ReportAdapter(None,None,None).parse(path,{**JOB,"file_name":path.name})
    same=FakeConn(existing=("other-hash",JOB["request_payload"]["documentId"]))
    assert timescale.write_package(same,pkg,accept_source_errors=True)["status"]=="written"
    assert any(s.startswith("DELETE FROM km_test.test_run") for s,_ in same.log)
    other=FakeConn(existing=("other-hash","99999999-9999-4999-8999-999999999999"))
    with pytest.raises(timescale.ConflictError):timescale.write_package(other,pkg,accept_source_errors=True)
    unchanged=FakeConn(existing=(pkg["source"]["checksum"],None))
    assert timescale.write_package(unchanged,pkg,accept_source_errors=True)["status"]=="unchanged"

@pytest.mark.skipif(not SAMPLES,reason="set WIFI_REPORT_SAMPLES to the Wi-Fi sample report folder")
def test_graph_and_vector_provenance_follow_csit_policy():
    import re
    from src.report_numeric import graph,vector
    path=Path(SAMPLES)/JOB["file_name"]
    pkg=ReportAdapter(None,None,None).parse(path,{**JOB,"file_name":path.name})
    runs=[]
    class Session:
        def run(self,query,**params):runs.append((query,params))
    graph.write_graph(Session(),pkg)
    for query,params in runs:
        if "$" in query:assert set(re.findall(r"\$(\w+)",query))<=set(params),query[:80]   # every Cypher parameter is bound
    merged=[p for q,p in runs if "approval_basis" in q][0]
    assert (merged["ss"],merged["ab"],merged["idb"])==("CSIT","csit","csit")
    assert not any("'ManualUpload'" in q for q,_ in runs)
    payload=vector.payload(pkg,{"chunk_id":"c","chunk_index":0,"chunk_hash":"h","text":"t","content_type":"x"},"m","v1")
    assert (payload["source_system"],payload["approval_basis"])==("CSIT","csit") and payload["source_record_id"].endswith(":v3")
