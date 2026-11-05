"""Simulator vs spec v1.4.1: it must refuse a KM that guesses ids, uses old scope names, fakes success, or sends the wrong event."""
import base64,copy,uuid
import pytest
from fastapi.testclient import TestClient
from tools.csit_simulator.checks import check_job_callback_v2,check_report_callback_v1,NEVER_RETRY
from tools.csit_simulator.identity import Identity,OUTBOUND_SCOPES,OUTBOUND_SCOPES_V14
from tools.csit_simulator.sim import Sim
from tools.csit_simulator.app import create_app
from test_simulator_v2 import RESULT,job_cb,cb_url

H={"Authorization":"Bearer t"}
BASE="/api/integrations/km"

@pytest.fixture
def api(monkeypatch):
    sim=Sim("http://km.invalid","t")
    def fake_post(url,json=None,headers=None,**k):
        if url.endswith("/v1/ingestion-jobs"):body={"jobId":"7d1c3a54-0000-4000-8000-000000000001","sourceSystem":"CSIT","documentId":json["documentId"],"version":json["version"],"status":"Accepted"}
        elif url.endswith("/v1/document-library/jobs"):body={"csitJobId":json["csitJobId"],"kmJobId":"KM-DOC-000001","status":"Accepted"}
        elif "document-jobs" in url:body={"eventId":json["eventId"],"csitJobId":json["csitJobId"],"kmJobId":"KM-ING-000001","status":"Accepted"}
        else:body={"deletionRequestId":json["deletionRequestId"],"kmDeletionJobId":"KM-DEL-000001","status":"Accepted"}
        fake_post.sent.append((url,json,headers));return type("R",(),{"status_code":202,"text":"","json":lambda self:body})()
    fake_post.sent=[]
    monkeypatch.setattr("tools.csit_simulator.sim.httpx.post",fake_post);monkeypatch.setattr("tools.csit_simulator.v2.httpx.post",fake_post)
    with TestClient(create_app(sim)) as c:yield c,sim,fake_post

def new(c,st,**kw):return c.post("/api/docs",json={"contentText":"hello world text","sourceType":st,"autoRun":True,**kw}).json()
def report_cb(doc,status,**kw):
    p={"jobId":"7d1c3a54-0000-4000-8000-000000000001","sourceSystem":"CSIT","documentId":doc["id"],"version":doc["version"],"status":status,
       "timestamps":{"updatedAt":"2026-11-05T01:08:00Z"}}
    if status=="Processing":p["timestamps"]["startedAt"]="2026-11-05T01:08:00Z"
    if status=="Completed":p["timestamps"]["completedAt"]="2026-11-05T01:08:25Z"
    if status=="Failed":p["timestamps"]["failedAt"]="2026-11-05T01:08:25Z";p["error"]={"code":"X","message":"m"}
    p.update(kw);return p
def report_ok(c,doc):
    for st in ("Processing","Completed"):assert c.post(BASE+"/v1/ingestion-status",json=report_cb(doc,st),headers=H).status_code==204

# ---------- routing and the Test Report notice ----------
def test_routes_follow_spec_answer_5(api):
    c,sim,post=api
    assert sim.route(new(c,"DocumentLibraryFile"))=="v1" and sim.route(new(c,"TestReport"))=="report1" and sim.route(new(c,"VendorFile"))=="v2"
    old=new(c,"TestReport");nw=new(c,"TestReport",supersedesDocId=old["id"])
    assert sim.route(nw)=="v2" and post.sent[-1][1]["eventType"]=="TestReportCommitted" and post.sent[-1][1]["supersedes"]["oldDocumentId"]==old["id"]
    lib=new(c,"DocumentLibraryFile");nl=new(c,"DocumentLibraryFile",supersedesDocId=lib["id"])
    assert sim.route(nl)=="v2" and post.sent[-1][1]["eventType"]=="DocumentLibraryFileUploaded"

def test_test_report_v1_notice_and_its_distinct_ids(api):
    c,sim,post=api
    d=new(c,"TestReport");url,body,_=post.sent[-1]
    assert url.endswith("/api/integrations/csit/v1/ingestion-jobs") and body["eventType"]=="TestReportCommitted" and body["eventId"]==d["eventId"]
    assert set(body)=={"eventId","eventType","sourceSystem","documentId","version","project","case","task","document","committedAt"}   # no sourceEntityId, no csitJobId
    assert d["entityId"]!=d["id"] and d["outboxId"]!=d["eventId"] and {d["entityId"],d["outboxId"],d["eventId"],d["id"]}.__len__()==4
    assert body["document"]=={"fileName":d["name"],"contentType":"text/plain","sizeBytes":d["size"]}

def test_test_report_file_is_served_with_content_type_and_filename(api):
    c,sim,post=api
    d=new(c,"TestReport",fileName="報告.txt");r=c.get(f"{BASE}/v1/documents/{d['id']}/versions/1/content",headers=H)
    assert r.status_code==200 and r.headers["content-type"].startswith("text/plain") and "filename*=UTF-8''" in r.headers["content-disposition"]
    e=new(c,"TestReport",fileName="a.txt");assert 'filename="a.txt"' in c.get(f"{BASE}/v1/documents/{e['id']}/versions/1/content",headers=H).headers["content-disposition"]

# ---------- v1 callbacks for a report ----------
def test_report_v1_callback_rules():
    ok={"jobId":"j","sourceSystem":"CSIT","documentId":str(uuid.uuid4()),"version":1,"status":"Completed","timestamps":{"updatedAt":"2026-11-05T01:08:00Z","completedAt":"2026-11-05T01:08:00Z"}}
    assert check_report_callback_v1(ok)==[]
    assert any("no result" in x for x in check_report_callback_v1({**ok,"result":{}}))
    assert check_report_callback_v1({**ok,"timestamps":{"updatedAt":"2026-11-05T01:08:00Z"}})
    assert check_report_callback_v1({**ok,"status":"Failed"})
    assert check_report_callback_v1({**ok,"version":0}) and check_report_callback_v1({**ok,"documentId":"x"})

def test_report_v1_callbacks_are_correlated_and_ordered(api):
    c,sim,post=api;d=new(c,"TestReport")
    p=report_cb(d,"Processing");assert c.post(BASE+"/v1/ingestion-status",json=p,headers=H).status_code==204
    assert c.post(BASE+"/v1/ingestion-status",json=p,headers=H).status_code==204                                 # same content: idempotent
    assert c.post(BASE+"/v1/ingestion-status",json=report_cb(d,"Processing",jobId="other"),headers=H).status_code==409
    assert c.post(BASE+"/v1/ingestion-status",json=report_cb(d,"Completed",result={"x":1}),headers=H).status_code==400
    assert c.post(BASE+"/v1/ingestion-status",json=report_cb(d,"Completed"),headers=H).status_code==204
    assert c.post(BASE+"/v1/ingestion-status",json=report_cb(d,"Failed",timestamps={"updatedAt":"2026-11-05T01:09:00Z","failedAt":"2026-11-05T01:09:00Z"}),headers=H).status_code==409
    assert c.post(BASE+"/v1/ingestion-status",json=report_cb({"id":str(uuid.uuid4()),"version":1},"Processing"),headers=H).status_code==404

# ---------- Correlation Resolver ----------
Q=lambda d,**o:{"documentId":d["id"],"version":d["version"],"kmJobId":"7d1c3a54-0000-4000-8000-000000000001",**o}
def resolve(c,d,**o):
    q=Q(d,**o);return c.get(f"{BASE}/v2/test-report-correlations/{o.pop('eventId',d['eventId'])}",params={k:v for k,v in q.items() if k!="eventId"},headers=H)

def test_resolver_answers_exactly_c2_only_after_v1_completed(api):
    c,sim,post=api;d=new(c,"TestReport")
    early=resolve(c,d);assert early.status_code==409 and early.json()["code"]=="job_not_completed"
    assert any(not v["ok"] and "before its v1 Completed" in v["what"] for v in sim.view(sim.docs[d["id"]])["allVerdicts"])   # asking early is KM's mistake
    report_ok(c,d)
    r=resolve(c,d)
    assert r.status_code==200 and r.headers["cache-control"]=="no-store"
    assert r.json()=={"schemaVersion":"2.0","sourceSystem":"CSIT","sourceType":"TestReport","eventId":d["eventId"],"sourceEntityId":d["entityId"],"documentId":d["id"],
        "version":1,"csitJobId":d["outboxId"],"kmJobId":"7d1c3a54-0000-4000-8000-000000000001","sourceSha256":d["sha256"],"status":"Completed"}
    assert r.json()["sourceEntityId"]!=r.json()["documentId"] and r.json()["csitJobId"]!=r.json()["eventId"]

def test_resolver_refusals(api):
    c,sim,post=api;d=new(c,"TestReport");report_ok(c,d)
    assert c.get(f"{BASE}/v2/test-report-correlations/{uuid.uuid4()}",params=Q(d),headers=H).status_code==404
    assert c.get(f"{BASE}/v2/test-report-correlations/{d['eventId']}",params=Q(d,version=2),headers=H).status_code==409
    assert c.get(f"{BASE}/v2/test-report-correlations/{d['eventId']}",params=Q(d,kmJobId="KM-OTHER"),headers=H).status_code==409
    assert c.get(f"{BASE}/v2/test-report-correlations/{d['eventId']}",params=Q(d,documentId=str(uuid.uuid4())),headers=H).status_code==409
    assert c.get(f"{BASE}/v2/test-report-correlations/{d['eventId']}",params=Q(d)).status_code==401
    c.post("/api/callback-faults",json={"resolver":"notdeployed"})
    assert resolve(c,d).status_code==404
    c.post("/api/callback-faults",json={"resolver":"unavailable"});assert resolve(c,d).status_code==503
    c.post("/api/callback-faults",json={"resolver":"ok"})
    sim.docs[d["id"]]["stage"]="Deleting";assert resolve(c,d).status_code==410

# ---------- analysis-results ----------
def analysis(d,**over):
    p={"schemaVersion":"2.0","analysisResultId":str(uuid.uuid4()),"callbackId":str(uuid.uuid4()),"sourceSystem":"CSIT","sourceType":"TestReport",
       "sourceEntityId":d["entityId"],"documentId":d["id"],"version":1,"csitJobId":d["outboxId"],"kmJobId":"7d1c3a54-0000-4000-8000-000000000001",
       "sourceSha256":d["sha256"],"metadataSchemaVersion":"2.0","result":copy.deepcopy(RESULT),"analyzedAt":"2026-11-05T01:08:25Z","supersedesAnalysisResultId":None}
    p.update(over);return p
def send(c,p,key=True):return c.post(BASE+"/v2/analysis-results",json=p,headers={**H,"Idempotency-Key":p["callbackId"]} if key else H)
def bad(sim,d):return [v["what"] for v in sim.view(sim.docs[d["id"]])["allVerdicts"] if not v["ok"]]

def test_analysis_results_with_the_resolved_ids_is_accepted(api):
    c,sim,post=api;d=new(c,"TestReport");report_ok(c,d);assert resolve(c,d).status_code==200
    p=analysis(d);assert send(c,p).status_code==204 and send(c,p).status_code==204 and not bad(sim,d)               # twice: idempotent
    assert sim.docs[d["id"]]["analysis"]["metadataSchemaVersion"]=="2.0"
    assert send(c,{**p,"analysisResultId":str(uuid.uuid4())}).status_code==409                                      # same callbackId, other body

@pytest.mark.parametrize("name,over",[("documentId used as sourceEntityId",lambda d:{"sourceEntityId":d["id"]}),
                                      ("eventId used as csitJobId",lambda d:{"csitJobId":d["eventId"]}),
                                      ("wrong source hash",lambda d:{"sourceSha256":"b"*64}),("wrong kmJobId",lambda d:{"kmJobId":"KM-OTHER"})])
def test_guessed_ids_are_refused_and_flagged(api,name,over):
    c,sim,post=api;d=new(c,"TestReport");report_ok(c,d);resolve(c,d)
    assert send(c,analysis(d,**over(d))).status_code==409 and bad(sim,d),name

def test_analysis_without_asking_the_resolver_or_before_v1_completed_is_flagged(api):
    c,sim,post=api;d=new(c,"TestReport")
    r=send(c,analysis(d));assert r.status_code==409 and r.json()["detail"]["code"]=="job_not_completed"
    assert any("before the v1 Completed" in x for x in bad(sim,d))
    report_ok(c,d);assert send(c,analysis(d)).status_code==204
    assert any("without asking the Correlation Resolver" in x for x in bad(sim,d))

def test_analysis_needs_the_idempotency_key_and_a_valid_result(api):
    c,sim,post=api;d=new(c,"TestReport");report_ok(c,d);resolve(c,d)
    assert send(c,analysis(d),key=False).status_code==204 and any("Idempotency-Key" in x for x in bad(sim,d))
    broken=analysis(d);broken["result"].pop("sourceSpecific")
    assert send(c,broken).status_code==400
    assert send(c,analysis({**d,"id":str(uuid.uuid4())},documentId=str(uuid.uuid4()))).status_code==404

# ---------- false success, retry flags, scopes ----------
def test_false_success_and_retryable_integrity_failures_are_violations():
    d={"sourceType":"VendorFile","entityId":str(uuid.uuid4()),"id":str(uuid.uuid4()),"version":1,"sha256":"a"*64};j={"eventId":str(uuid.uuid4()),"csitJobId":str(uuid.uuid4())}
    none=job_cb("Completed",d,j);none["result"]["extraction"]["method"]="None"
    zero=job_cb("Completed",d,j);zero["result"]["indexing"]["chunkCount"]=0
    for p in (none,zero):assert any("false success" in x for x in check_job_callback_v2(p))
    for code in NEVER_RETRY:
        f=job_cb("Failed",d,j);f["error"]={"code":code,"message":"m","retryable":True}
        assert any("retryable=false" in x for x in check_job_callback_v2(f)),code
    ok=job_cb("Failed",d,j);ok["error"]={"code":"UNSUPPORTED_FORMAT","message":"m","retryable":False};assert check_job_callback_v2(ok)==[]
    other=job_cb("Failed",d,j);other["error"]={"code":"STORAGE_UNAVAILABLE","message":"m","retryable":True};assert check_job_callback_v2(other)==[]
    for src in ("TestReport","DocumentLibraryFile"):assert check_job_callback_v2(job_cb("Completed",{**d,"sourceType":src},j))==[]

def test_v2_callbacks_demand_the_official_scopes_and_not_the_old_ones(tmp_path):
    ident=Identity("https://sim/","km-api","csit-api","km-client","secret","csit-sim")
    sim=Sim("http://km.invalid","t",identity=ident)
    basic="Basic "+base64.b64encode(b"km-client:secret").decode()
    def token(scopes):
        st,b=ident.token_endpoint(basic,("grant_type=client_credentials&scope="+"+".join(scopes)).encode());assert st==200;return {"Authorization":"Bearer "+b["access_token"]}
    d=sim.create_doc({"contentText":"x","sourceType":"VendorFile"});job={"eventId":str(uuid.uuid4()),"csitJobId":str(uuid.uuid4())}
    with TestClient(create_app(sim)) as c:
        url=lambda p:"/api/integrations/km"+p
        f=lambda scopes,path,**kw:c.post(url(path),json=job_cb("Processing",d,job),headers=token(scopes)).status_code
        assert f(OUTBOUND_SCOPES,"/v2/document-jobs/status")==401                      # v1.3 scopes are not enough for a v2 callback
        assert f(("csit.document.read","csit.km.deletion-status.write"),"/v2/document-jobs/status")==401
        assert f(("csit.km.status.write",),"/v2/document-jobs/status")!=401
        assert c.get(url("/v1/vendor-files/"+d["id"]+"/content"),headers=token(("csit.km.status.write",))).status_code==401
        assert c.get(url("/v1/vendor-files/"+d["id"]+"/content"),headers=token(OUTBOUND_SCOPES_V14)).status_code in (200,404)
        assert "csit.documents.read" not in OUTBOUND_SCOPES_V14                      # singular document, as C.3 says
        assert ident.token_endpoint(basic,b"grant_type=client_credentials&scope=csit.documents.read")[0]==400
