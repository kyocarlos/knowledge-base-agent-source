"""The simulator must be able to say no: feed it callbacks KM must never send."""
import copy,uuid
import pytest
from fastapi.testclient import TestClient
from tools.csit_simulator.checks import check_ingestion_callback,check_deletion_callback,CLEANUP
from tools.csit_simulator.sim import Sim
from tools.csit_simulator.app import create_app

RESULT={"metadataSchemaVersion":"1.0",
 "document":{"title":None,"documentType":"Other","summary":None,"language":None,"documentDate":None,"authors":[],"department":None,"documentVersionLabel":None,"keywords":[],"tags":[]},
 "technical":{k:[] for k in ("productNames","modelNumbers","vendorNames","technologies","standards","softwareVersions","hardwareVersions","projectNames","testItems","measurements","issueKeys","errorCodes")},
 "extraction":{"sourceFormat":"pdf","method":"Text","pageCount":1,"sheetNames":[],"extractedCharacterCount":20,"ocrUsed":False},
 "indexing":{"status":"Completed","indexId":"KM-INDEX-0001","chunkCount":1,"indexedAt":"2026-11-04T01:59:58Z"},"warnings":[]}
def cb(status,job,**kw):
    ts={"startedAt":None,"completedAt":None,"failedAt":None}
    p={"schemaVersion":"1.0","callbackId":str(uuid.uuid4()),"sourceSystem":"CSIT","documentFileId":job["documentFileId"],"csitJobId":job["csitJobId"],
       "kmJobId":job["kmJobId"],"status":status,"timestamps":ts,"result":None,"error":None}
    if status=="Processing":ts["startedAt"]="2026-11-04T02:00:00Z"
    if status=="Completed":ts["completedAt"]="2026-11-04T02:00:00Z";p["result"]=copy.deepcopy(RESULT)
    if status=="Failed":ts["failedAt"]="2026-11-04T02:00:00Z";p["error"]={"code":"X","message":"m","retryable":False}
    p.update(kw);return p

def test_spec_fixture_passes_and_each_defect_is_caught():
    job={"documentFileId":str(uuid.uuid4()),"csitJobId":str(uuid.uuid4()),"kmJobId":"KM-DOC-1"}
    assert check_ingestion_callback(cb("Completed",job))==[]
    bad=cb("Completed",job);del bad["result"]["technical"]["errorCodes"]
    assert any("errorCodes" in p for p in check_ingestion_callback(bad))
    bad=cb("Completed",job);bad["result"]["document"]["documentType"]="Poem"
    assert any("documentType" in p for p in check_ingestion_callback(bad))
    bad=cb("Completed",job);bad["result"]["indexing"]["indexId"]=""
    assert any("indexId" in p for p in check_ingestion_callback(bad))
    bad=cb("Processing",job);bad["timestamps"]["startedAt"]=None
    assert check_ingestion_callback(bad)
    bad=cb("Failed",job);bad["error"].pop("retryable")
    assert check_ingestion_callback(bad)
    bad=cb("Completed",job);del bad["timestamps"]["failedAt"]
    assert any("timestamps" in p for p in check_ingestion_callback(bad))

def test_deletion_completed_needs_all_seven_verified_items():
    base={"schemaVersion":"1.0","callbackId":str(uuid.uuid4()),"sourceSystem":"CSIT","deletionRequestId":str(uuid.uuid4()),"kmDeletionJobId":"KM-DEL-1",
          "resource":{},"status":"Completed","timestamps":{"startedAt":None,"completedAt":"2026-11-04T02:03:00Z","failedAt":None},"error":None,
          "result":{"cleanupVerified":True,"verifiedAt":"2026-11-04T02:02:58Z","cleanup":{k:"Deleted" for k in CLEANUP}}}
    assert check_deletion_callback(base)==[]
    bad=copy.deepcopy(base);bad["result"]["cleanup"]["cache"]="Unverified";assert check_deletion_callback(bad)
    bad=copy.deepcopy(base);bad["result"]["cleanup"].pop("cache");assert check_deletion_callback(bad)
    bad=copy.deepcopy(base);bad["result"]["cleanupVerified"]=False;assert check_deletion_callback(bad)

@pytest.fixture
def api(monkeypatch):
    sim=Sim("http://km.invalid","t")
    def fake_post(url,json=None,**k):
        body={"deletionRequestId":json["deletionRequestId"],"kmDeletionJobId":"KM-DEL-1","status":"Accepted"} if "deletionRequestId" in json             else {"csitJobId":json["csitJobId"],"kmJobId":"KM-DOC-1","status":"Accepted"}
        return type("R",(),{"status_code":202,"text":"","json":lambda self:body})()
    monkeypatch.setattr("tools.csit_simulator.sim.httpx.post",fake_post)
    with TestClient(create_app(sim)) as c:
        d=c.post("/api/docs",json={"contentText":"hello world text","autoRun":True}).json()
        job=d["jobs"][0]|{"documentFileId":d["id"]};yield c,sim,job
H={"Authorization":"Bearer t"}
URL="/api/integrations/km/v1/document-library/ingestion-status"

def test_simulator_rejects_what_km_must_never_send(api):
    c,sim,job=api
    assert c.post(URL,json=cb("Processing",job)).status_code==401
    assert c.post(URL,json=cb("Processing",job),headers=H).status_code==204
    p=cb("Completed",job);assert c.post(URL,json=p,headers=H).status_code==204
    assert c.post(URL,json=p,headers=H).status_code==204 # same callbackId, same body: idempotent
    clash=copy.deepcopy(p);clash["result"]["indexing"]["chunkCount"]=9
    assert c.post(URL,json=clash,headers=H).status_code==409
    assert c.post(URL,json=cb("Processing",job),headers=H).status_code==409 # late Processing after Completed
    other=cb("Completed",job,kmJobId="KM-DOC-OTHER");assert c.post(URL,json=other,headers=H).status_code==409
    assert c.post(URL,json={"status":"Completed"},headers=H).status_code in (400,404)
    r=c.get("/api/report").json();assert r["failed"]>=3 and r["violations"]

def test_simulator_serves_only_known_live_files_with_auth(api):
    c,sim,job=api
    path="/api/integrations/km/v1/document-library/files/%s/content"%job["documentFileId"]
    assert c.get(path).status_code==401
    assert c.get(path,headers=H).content==b"hello world text"
    assert c.get(path.replace(job["documentFileId"],str(uuid.uuid4())),headers=H).status_code==404
    c.post("/api/docs/%s/delete"%job["documentFileId"],json={});sim.dels and None
    # CSIT keeps serving until KM verifies the cleanup
    assert c.get(path,headers=H).status_code==200
    sim.docs[job["documentFileId"]]["content"]=None # what KM's verified Completed callback triggers
    assert c.get(path,headers=H).status_code==404

def test_workflow_order_is_enforced_by_csit():
    sim=Sim("http://km.invalid","t")
    with TestClient(create_app(sim)) as c:
        d=c.post("/api/docs",json={"contentText":"x y z"}).json()
        assert d["stage"]=="PendingApproval" and d["jobIds"]==[]
        assert c.post("/api/docs/%s/archive"%d["id"]).status_code==409   # cannot archive before approval
        assert c.post("/api/docs/%s/dispatch"%d["id"]).status_code==409  # KM is told only after the NAS archive
        path="/api/integrations/km/v1/document-library/files/%s/content"%d["id"]
        assert c.get(path,headers={"Authorization":"Bearer t"}).status_code==404 # not archived: nothing to download
