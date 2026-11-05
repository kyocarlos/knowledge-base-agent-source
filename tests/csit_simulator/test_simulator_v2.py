"""The simulator must be able to say no to a v1.4 KM, and must serve the files KM fetches for each source."""
import copy,uuid
import pytest
from fastapi.testclient import TestClient
from tools.csit_simulator.checks import (check_job_callback_v2,check_change_callback,check_deletion_callback_v2,check_analysis_result,CLEANUP)
from tools.csit_simulator.sim import Sim
from tools.csit_simulator.app import create_app

H={"Authorization":"Bearer t","Idempotency-Key":""}
RESULT={"metadataSchemaVersion":"2.0",
 "document":{"title":None,"documentType":"Other","summary":None,"language":None,"documentDate":None,"authors":[],"department":None,"documentVersionLabel":None,"keywords":[],"tags":[]},
 "technical":{k:[] for k in ("productNames","modelNumbers","vendorNames","technologies","standards","softwareVersions","hardwareVersions","projectNames","testItems","measurements","issueKeys","errorCodes")},
 "extraction":{"sourceFormat":"xlsx","method":"Text","pageCount":None,"sheetNames":["Sheet1"],"extractedCharacterCount":70,"ocrUsed":False},
 "indexing":{"status":"Completed","indexId":"km-idx-01","chunkCount":1,"indexedAt":"2026-11-05T01:08:24Z"},"warnings":[],"sourceSpecific":{}}

def job_cb(status,doc,job,**kw):
    ts={"startedAt":"2026-11-05T01:08:00Z","completedAt":None,"failedAt":None}
    p={"schemaVersion":"2.0","callbackId":str(uuid.uuid4()),"eventId":job["eventId"],"csitJobId":job["csitJobId"],"kmJobId":"KM-ING-000001","sourceSystem":"CSIT",
       "sourceType":doc["sourceType"],"sourceEntityId":doc["entityId"],"documentId":doc["id"],"version":doc["version"],"sourceSha256":doc["sha256"],
       "status":status,"timestamps":ts,"result":None,"error":None}
    if status=="Completed":ts["completedAt"]="2026-11-05T01:08:25Z";p["result"]=copy.deepcopy(RESULT)
    if status=="Failed":ts["failedAt"]="2026-11-05T01:08:10Z";p["error"]={"code":"ENCRYPTED_DOCUMENT","message":"m","retryable":False}
    p.update(kw);return p

def test_v2_job_callback_defects_are_caught():
    d={"sourceType":"VendorFile","entityId":str(uuid.uuid4()),"id":str(uuid.uuid4()),"version":1,"sha256":"a"*64}
    j={"eventId":str(uuid.uuid4()),"csitJobId":str(uuid.uuid4())}
    assert check_job_callback_v2(job_cb("Completed",d,j))==[]
    assert check_job_callback_v2(job_cb("Failed",d,j))==[]
    for mutate,needle in ((lambda p:p.update(schemaVersion="1.0"),"schemaVersion"),(lambda p:p["result"].pop("sourceSpecific"),"sourceSpecific"),
        (lambda p:p["result"]["extraction"].update(method="Magic"),"method"),(lambda p:p.update(sourceSha256="zz"),"sourceSha256"),
        (lambda p:p.update(sourceType="Nope"),"sourceType"),(lambda p:p["timestamps"].pop("failedAt"),"timestamps"),
        (lambda p:p.update(version=0),"version"),(lambda p:p.pop("eventId"),"eventId"),
        (lambda p:p["result"]["extraction"].update(ocrUsed=True),"ocrUsed")):
        p=job_cb("Completed",d,j);mutate(p)
        assert any(needle in x for x in check_job_callback_v2(p)),needle
    assert check_job_callback_v2(job_cb("Completed",d,j,error={"code":"X","message":"m","retryable":False}))
    assert check_job_callback_v2(job_cb("Failed",d,j,result=copy.deepcopy(RESULT)))
    ok=job_cb("Completed",d,j);ok["result"]["extraction"]["method"]="Visual";assert check_job_callback_v2(ok)==[]

def test_change_callback_rules():
    base={"schemaVersion":"2.0","callbackId":str(uuid.uuid4()),"changeId":str(uuid.uuid4()),"kmChangeJobId":"KM-CHANGE-1","sourceSystem":"CSIT",
          "status":"Completed","appliedRevision":2,"timestamps":{"startedAt":"2026-11-05T02:00:05Z","completedAt":"2026-11-05T02:00:12Z","failedAt":None},"error":None}
    assert check_change_callback(base)==[]
    assert check_change_callback({**base,"appliedRevision":None})
    assert check_change_callback({**base,"schemaVersion":"1.0"})
    assert check_change_callback({**base,"status":"Failed","error":None,"timestamps":{**base["timestamps"],"failedAt":"2026-11-05T02:00:12Z"}})

def test_v2_deletion_callback_rules_and_analysis_shape():
    base={"schemaVersion":"2.0","callbackId":str(uuid.uuid4()),"sourceSystem":"CSIT","deletionRequestId":str(uuid.uuid4()),"kmDeletionJobId":"KM-DEL-1","resource":{},
          "status":"Completed","timestamps":{"startedAt":"2026-11-05T03:00:10Z","completedAt":"2026-11-05T03:01:00Z","failedAt":None},"error":None,
          "result":{"cleanupVerified":True,"verifiedAt":"2026-11-05T03:00:58Z","cleanup":{k:"Deleted" for k in CLEANUP}}}
    assert check_deletion_callback_v2(base)==[]
    assert check_deletion_callback_v2({**base,"schemaVersion":"1.0"})
    bad=copy.deepcopy(base);bad["result"]["cleanup"]["cache"]="Pending";assert check_deletion_callback_v2(bad)
    ar={"schemaVersion":"2.0","analysisResultId":str(uuid.uuid4()),"callbackId":str(uuid.uuid4()),"sourceSystem":"CSIT","sourceType":"TestReport",
        "sourceEntityId":str(uuid.uuid4()),"documentId":str(uuid.uuid4()),"version":1,"csitJobId":str(uuid.uuid4()),"kmJobId":"KM-REPORT-1","sourceSha256":"a"*64,
        "metadataSchemaVersion":"2.0","result":copy.deepcopy(RESULT),"analyzedAt":"2026-11-05T01:08:25Z","supersedesAnalysisResultId":None}
    assert check_analysis_result(ar)==[]
    assert check_analysis_result({**ar,"sourceType":"VendorFile"})

@pytest.fixture
def api(monkeypatch):
    sim=Sim("http://km.invalid","t")
    def fake_post(url,json=None,headers=None,**k):
        if "document-jobs" in url:body={"eventId":json["eventId"],"csitJobId":json["csitJobId"],"kmJobId":"KM-ING-000001","status":"Accepted"}
        elif "metadata-changes" in url:body={"changeId":json["changeId"],"kmChangeJobId":"KM-CHANGE-000001","status":"Accepted"}
        else:body={"deletionRequestId":json["deletionRequestId"],"kmDeletionJobId":"KM-DEL-000001","status":"Accepted"}
        fake_post.sent.append((url,json,headers));return type("R",(),{"status_code":202,"text":"","json":lambda self:body})()
    fake_post.sent=[]
    monkeypatch.setattr("tools.csit_simulator.sim.httpx.post",fake_post);monkeypatch.setattr("tools.csit_simulator.v2.httpx.post",fake_post)
    with TestClient(create_app(sim)) as c:yield c,sim,fake_post

def new(c,st,**kw):
    return c.post("/api/docs",json={"contentText":"hello world text","sourceType":st,"autoRun":True,**kw}).json()

@pytest.mark.parametrize("st,path",[("VerificationApplicationAttachment","/documents/{id}/versions/1/content"),("VendorFile","/vendor-files/{id}/content"),
                                    ("EquipmentAttachment","/equipment-documents/{id}/content")])
def test_each_source_is_served_only_from_its_own_route(api,st,path):
    c,sim,post=api
    d=new(c,st);base="/api/integrations/km/v1"
    ok=c.get(base+path.format(id=d["id"]),headers=H)
    assert ok.status_code==200 and ok.content==b"hello world text"
    assert d["downloadPath"]==base+path.format(id=d["id"])
    others=[p for p in ("/documents/{id}/versions/1/content","/vendor-files/{id}/content","/equipment-documents/{id}/content","/document-library/files/{id}/content") if p!=path]
    for o in others:assert c.get(base+o.format(id=d["id"]),headers=H).status_code==404   # a vendor file is not reachable as an equipment document
    if "/versions/" in path:assert c.get(base+path.format(id=d["id"]).replace("/versions/1","/versions/2"),headers=H).status_code==404   # the version is part of the identity
    assert c.get(base+path.format(id=d["id"])).status_code==401

def test_v2_notice_follows_the_spec_shape(api):
    c,sim,post=api
    d=new(c,"VerificationApplicationAttachment")
    url,body,headers=post.sent[-1]
    assert url.endswith("/api/integrations/csit/v2/document-jobs") and headers["Idempotency-Key"]==body["eventId"]
    assert body["schemaVersion"]=="2.0" and body["eventType"]=="VerificationApplicationAttachmentArchived" and body["eventId"]!=body["csitJobId"]
    assert body["source"]["entityId"]!=body["document"]["id"] and body["document"]["approval"]["mode"]=="Approved" and body["document"]["archivedAt"]
    assert body["supersedes"] is None and set(body["classification"])=={"l1","l2","l3"}
    v=new(c,"VendorFile");vb=post.sent[-1][1]
    assert vb["source"]["entityId"]==vb["document"]["id"] and vb["source"]["vendorId"] and vb["eventType"]=="VendorFileArchived"
    nv=new(c,"VendorFile",supersedesDocId=v["id"]);nb=post.sent[-1][1]
    assert nb["supersedes"]=={"oldDocumentId":v["id"],"oldVersion":1,"oldSha256":v["sha256"]} and nb["document"]["version"]==2

def test_a_pending_v2_document_does_not_reach_km_and_unknown_sources_are_refused(api):
    c,sim,post=api
    d=c.post("/api/docs",json={"contentText":"x","sourceType":"VendorFile"}).json()
    assert post.sent==[] and c.post(f"/api/docs/{d['id']}/dispatch").status_code==409
    assert c.post("/api/docs",json={"contentText":"x","sourceType":"Nope"}).status_code==400

def cb_url(kind):return {"jobs":"/api/integrations/km/v2/document-jobs/status","changes":"/api/integrations/km/v2/document-metadata-changes/status",
                         "deletions":"/api/integrations/km/v2/document-deletions/status"}[kind]

def test_callbacks_are_judged_for_headers_correlation_and_order(api):
    c,sim,post=api
    d=new(c,"VendorFile");job=d["jobs"][0]
    ok=job_cb("Processing",d,job)
    assert c.post(cb_url("jobs"),json=ok,headers={**H,"Idempotency-Key":ok["callbackId"]}).status_code==204
    assert c.post(cb_url("jobs"),json=ok,headers={**H,"Idempotency-Key":ok["callbackId"]}).status_code==204        # same body again: idempotent
    assert c.post(cb_url("jobs"),json={**ok,"eventId":str(uuid.uuid4())},headers={**H,"Idempotency-Key":ok["callbackId"]}).status_code==409
    wrong=job_cb("Completed",d,job,sourceSha256="b"*64)
    assert c.post(cb_url("jobs"),json=wrong,headers={**H,"Idempotency-Key":wrong["callbackId"]}).status_code==409   # echoed values must match the accepted job
    done=job_cb("Completed",d,job)
    assert c.post(cb_url("jobs"),json=done,headers=H).status_code==204                                              # delivered, but...
    assert any(not v["ok"] and "Idempotency-Key" in v["what"] for v in sim.view(sim.docs[d["id"]])["allVerdicts"])  # ...the missing key is a violation
    late=job_cb("Processing",d,job)
    assert c.post(cb_url("jobs"),json=late,headers={**H,"Idempotency-Key":late["callbackId"]}).status_code==409     # nothing after Completed
    assert c.post(cb_url("jobs"),json=job_cb("Processing",d,{"eventId":str(uuid.uuid4()),"csitJobId":str(uuid.uuid4())}),headers=H).status_code==404
    assert c.post(cb_url("jobs"),json={"x":1}).status_code==401

def test_change_and_deletion_callbacks_are_correlated(api):
    c,sim,post=api
    d=new(c,"EquipmentAttachment")
    c.post(f"/api/docs/{d['id']}/change",json={"tags":["a"]})
    x=sim.changes[sim.docs[d["id"]]["changeIds"][-1]]
    cb={"schemaVersion":"2.0","callbackId":str(uuid.uuid4()),"changeId":x["changeId"],"kmChangeJobId":"KM-CHANGE-000001","sourceSystem":"CSIT","status":"Completed",
        "appliedRevision":x["revision"]+1,"timestamps":{"startedAt":"2026-11-05T02:00:05Z","completedAt":"2026-11-05T02:00:12Z","failedAt":None},"error":None}
    assert c.post(cb_url("changes"),json=cb,headers={**H,"Idempotency-Key":cb["callbackId"]}).status_code==409     # appliedRevision must equal sourceRevision
    cb.update(appliedRevision=x["revision"],callbackId=str(uuid.uuid4()))
    assert c.post(cb_url("changes"),json=cb,headers={**H,"Idempotency-Key":cb["callbackId"]}).status_code==204
    c.post(f"/api/docs/{d['id']}/delete")
    dx=sim.dels[sim.docs[d["id"]]["delIds"][0]]
    dcb={"schemaVersion":"2.0","callbackId":str(uuid.uuid4()),"sourceSystem":"CSIT","deletionRequestId":dx["deletionRequestId"],"kmDeletionJobId":"KM-DEL-000001",
         "resource":{**dx["resource"],"version":9},"status":"Completed","timestamps":{"startedAt":"2026-11-05T03:00:10Z","completedAt":"2026-11-05T03:01:00Z","failedAt":None},
         "result":{"cleanupVerified":True,"verifiedAt":"2026-11-05T03:00:58Z","cleanup":{k:"Deleted" for k in CLEANUP}},"error":None}
    assert c.post(cb_url("deletions"),json=dcb,headers={**H,"Idempotency-Key":dcb["callbackId"]}).status_code==409   # resource must be echoed unchanged
    dcb.update(resource=dx["resource"],callbackId=str(uuid.uuid4()))
    assert c.post(cb_url("deletions"),json=dcb,headers={**H,"Idempotency-Key":dcb["callbackId"]}).status_code==204
    assert sim.docs[d["id"]]["stage"]=="Purged" and sim.docs[d["id"]]["content"] is None
    r=dx["resource"]
    assert set(r)=={"sourceType","sourceEntityId","documentId","version","sha256","applicationId","recordId","vendorId","equipmentId","canonicalIngestionEventId","scope"}
    assert r["scope"]=="DocumentVersion" and r["canonicalIngestionEventId"]==sim.jobs[sim.docs[d["id"]]["jobIds"][-1]]["eventId"]

def test_v14_scopes_are_accepted_by_the_identity_authority():
    from tools.csit_simulator.identity import Identity,OUTBOUND_SCOPES_V14,INBOUND_SCOPES_V14
    import base64
    ident=Identity("https://sim/","km-api","csit-api","km-client","secret","csit-sim")
    basic="Basic "+base64.b64encode(b"km-client:secret").decode()
    status,body=ident.token_endpoint(basic,("grant_type=client_credentials&scope="+"+".join(OUTBOUND_SCOPES_V14)).encode())
    assert status==200 and set(body["scope"].split())==set(OUTBOUND_SCOPES_V14)
    h="Bearer "+body["access_token"]
    assert ident.verify_from_km(h,("csit.document.read","csit.documents.read")) and ident.verify_from_km(h,("csit.km.deletion-status.write",))
    assert not ident.verify_from_km(h,"csit.ingestion.status.write")                          # a name that was not granted
    assert ident.token_endpoint(basic,b"grant_type=client_credentials&scope=other.scope")[0]==400
    import jwt
    claims=jwt.decode(ident.mint_for_km(INBOUND_SCOPES_V14["jobs"]),options={"verify_signature":False})
    assert claims["scope"]=="km.ingestion.write" and jwt.decode(ident.mint_for_km(),options={"verify_signature":False})["scope"]=="km.ingestion.submit"
