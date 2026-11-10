"""Simulator for KM's live-data mode: documents are tagged with the KM mode they were notified in, the live ones can be purged, and any id can be deleted."""
import uuid
import pytest
from fastapi.testclient import TestClient
from tools.csit_simulator.sim import Sim
from tools.csit_simulator.app import create_app

SHA="a"*64

@pytest.fixture
def api(monkeypatch):
    sim=Sim("http://km.invalid","t")
    mode={"v":"live"}
    def fake_post(url,json=None,headers=None,**k):
        if url.endswith("/v1/ingestion-jobs"):body={"jobId":"7d1c3a54-0000-4000-8000-000000000001","sourceSystem":"CSIT","documentId":json["documentId"],"version":json["version"],"status":"Accepted"}
        elif url.endswith("/v1/document-library/jobs"):body={"csitJobId":json["csitJobId"],"kmJobId":"KM-DOC-000001","status":"Accepted"}
        elif "document-jobs" in url:body={"eventId":json["eventId"],"csitJobId":json["csitJobId"],"kmJobId":"KM-ING-000001","status":"Accepted"}
        else:body={"deletionRequestId":json["deletionRequestId"],"kmDeletionJobId":"KM-DEL-%06d"%(len(fake_post.sent)+1),"status":"Accepted"}
        fake_post.sent.append((url,json,headers));return type("R",(),{"status_code":202,"text":"","json":lambda self:body})()
    fake_post.sent=[]
    def fake_get(url,**k):
        assert url.endswith("/health")
        return type("R",(),{"status_code":200,"text":"","json":lambda self:{"status":"ok","csitMode":mode["v"]}})()
    for m in ("sim","v2"):
        monkeypatch.setattr(f"tools.csit_simulator.{m}.httpx.post",fake_post);monkeypatch.setattr(f"tools.csit_simulator.{m}.httpx.get",fake_get)
    with TestClient(create_app(sim)) as c:yield c,sim,fake_post,mode

def new(c,st="DocumentLibraryFile",**kw):return c.post("/api/docs",json={"contentText":"hello world text","sourceType":st,"autoRun":True,**kw}).json()
def deletions(post):return [(u,b) for u,b,_ in post.sent if "deletion" in u]

def test_documents_are_tagged_with_the_mode_they_were_sent_in(api):
    c,sim,post,mode=api
    mode["v"]="sim";a=new(c);mode["v"]="live";b=new(c,"VendorFile");mode["v"]="real";d=new(c,"EquipmentAttachment")
    assert a["kmModes"]==["sim"] and b["kmModes"]==["live"] and d["kmModes"]==["real"]
    assert c.get("/api/km/mode").json()=={"csitMode":"real"}

def test_purge_needs_confirmation_and_only_touches_live_documents(api):
    c,sim,post,mode=api
    mode["v"]="sim";s=new(c);mode["v"]="live";l1=new(c);l2=new(c,"VendorFile");mode["v"]="live"
    assert c.post("/api/purge-live",json={}).status_code==400 and not deletions(post)
    r=c.post("/api/purge-live",json={"confirmLiveData":True}).json()
    assert r["requested"]==2 and {x["docId"] for x in r["results"]}=={l1["id"],l2["id"]} and s["id"] not in {x["docId"] for x in r["results"]}
    assert len(deletions(post))==2
    # a second purge does not send the same deletions again
    r2=c.post("/api/purge-live",json={"confirmLiveData":True}).json()
    assert r2["requested"]==0 and set(r2["alreadyDeletedOrDeleting"])=={l1["id"],l2["id"]} and len(deletions(post))==2

def test_purge_skips_documents_that_were_not_archived_or_not_dispatched(api):
    c,sim,post,mode=api
    pending=c.post("/api/docs",json={"contentText":"x"}).json()  # never approved or dispatched: has no live tag
    new(c)
    r=c.post("/api/purge-live",json={"confirmLiveData":True}).json()
    assert r["requested"]==1 and pending["id"] not in {x["docId"] for x in r["results"]}

def test_delete_by_id_v2_carries_the_given_ids_and_needs_confirmation_in_live_mode(api):
    c,sim,post,mode=api
    ev,doc,ent=str(uuid.uuid4()),str(uuid.uuid4()),str(uuid.uuid4())
    spec={"api":"v2","sourceType":"VendorFile","documentId":doc,"version":3,"sourceEntityId":ent,"sha256":SHA,"canonicalIngestionEventId":ev}
    assert c.post("/api/delete-by-id",json=spec).status_code==400 and not deletions(post)
    r=c.post("/api/delete-by-id",json={**spec,"confirmLiveData":True}).json()
    url,body=deletions(post)[-1]
    assert url.endswith("/api/integrations/csit/v2/document-deletions") and r["deleteState"]=="Accepted"
    res=body["resource"]
    assert (res["sourceType"],res["documentId"],res["version"],res["sourceEntityId"],res["sha256"],res["canonicalIngestionEventId"])==("VendorFile",doc,3,ent,SHA,ev)
    assert body["eventType"]=="DocumentDeletionRequested" and body["reasonCode"]=="SourceDeleted"
    # a document the simulator did not send is never part of a purge
    assert c.post("/api/purge-live",json={"confirmLiveData":True}).json()["requested"]==0

def test_delete_by_id_needs_no_confirmation_outside_live_mode(api):
    c,sim,post,mode=api
    mode["v"]="sim";doc=str(uuid.uuid4())
    r=c.post("/api/delete-by-id",json={"sourceType":"DocumentLibraryFile","documentFileId":doc})
    assert r.status_code==200 and deletions(post)[-1][1]["resource"]["documentFileId"]==doc

def test_delete_by_id_v1_test_report_uses_the_v1_route_and_identity(api):
    c,sim,post,mode=api
    doc,ent=str(uuid.uuid4()),str(uuid.uuid4())
    c.post("/api/delete-by-id",json={"api":"v1","sourceType":"TestReport","documentId":doc,"version":2,"sourceEntityId":ent,"confirmLiveData":True})
    url,body=deletions(post)[-1]
    assert url.endswith("/api/integrations/csit/v1/document-deletions") and body["reasonCode"]=="TestReportVersionDeleted"
    assert (body["resource"]["sourceType"],body["resource"]["documentId"],body["resource"]["version"],body["resource"]["sourceEntityId"])==("TestReport",doc,2,ent)

def test_delete_by_id_validates_the_spec(api):
    c,sim,post,mode=api
    base={"confirmLiveData":True}
    assert c.post("/api/delete-by-id",json={**base,"sourceType":"Nope","documentId":"x","version":1,"sourceEntityId":"y"}).status_code==400
    assert c.post("/api/delete-by-id",json={**base,"sourceType":"DocumentLibraryFile"}).status_code==400
    assert c.post("/api/delete-by-id",json={**base,"api":"v2","sourceType":"VendorFile","documentId":"x"}).status_code==400
    assert c.post("/api/delete-by-id",json={**base,"api":"v1","sourceType":"VendorFile","documentId":"x","version":1,"sourceEntityId":"y"}).status_code==400
    assert not deletions(post)

def test_delete_by_id_of_a_document_this_simulator_sent_reuses_it(api):
    c,sim,post,mode=api
    d=new(c)
    r=c.post("/api/delete-by-id",json={"sourceType":"DocumentLibraryFile","documentFileId":d["id"],"confirmLiveData":True}).json()
    assert r["id"]==d["id"] and not r.get("external") and len(deletions(post))==1

def test_a_second_delete_by_id_while_the_first_is_running_is_refused(api):
    c,sim,post,mode=api
    spec={"api":"v1","sourceType":"TestReport","documentId":str(uuid.uuid4()),"version":1,"sourceEntityId":str(uuid.uuid4()),"confirmLiveData":True}
    assert c.post("/api/delete-by-id",json=spec).status_code==200
    assert c.post("/api/delete-by-id",json=spec).status_code==409


# ---------- zones: the L1 names are the KM navigation zones ----------
def test_taxonomy_l1_names_are_the_nine_km_zones():
    from tools.csit_simulator.sim import TAXONOMY
    assert [n["name"] for n in TAXONOMY]==["WiFi 知識專區","行動通訊知識專區","固網寬頻知識專區","認證知識專區","產品驗證專區","設備儀器專區","實驗室管理專區","Confluence / Jira / TestRail 查詢專區","部門與公司文管專區"]


def test_only_a_test_report_has_a_zone_before_kms_llm_has_read_it(api):
    c,sim,post,mode=api
    rep=c.post("/api/docs",json={"contentText":"x","sourceType":"TestReport","classification":{"l1":"20"}}).json()
    assert rep["expectedZone"]=="產品驗證專區" and rep["classification"]["l1"]["name"]=="WiFi 知識專區"   # the picked classification is kept, not overwritten
    for source in ("DocumentLibraryFile","VendorFile","EquipmentAttachment","VerificationApplicationAttachment"):
        assert c.post("/api/docs",json={"contentText":"x","sourceType":source,"classification":{"l1":"40"}}).json()["expectedZone"] is None
