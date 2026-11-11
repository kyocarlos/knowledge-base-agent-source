"""CSIT x AI KM spec v1.3: document-library ingestion, verified deletion, tombstones."""
import hashlib,json,uuid,copy
from dataclasses import replace
from types import SimpleNamespace
import httpx,pytest
from fastapi.testclient import TestClient
from src.csit_integration_v1.api import create_app
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.doclib_models import (DocLibRequest,DeletionRequest,Resource,build_ingestion_callback,
    build_deletion_callback,validate_result,CLEANUP_ITEMS)
from src.csit_integration_v1.doclib_repository import DocLibRepository
from src.csit_integration_v1.doclib_client import DocLibClient
from src.csit_integration_v1.doclib_pipeline import DocLibPipeline,DocLibQdrantWriter,doclib_dir
from src.csit_integration_v1.doclib_deletion import DeletionExecutor
from src.csit_integration_v1.doclib_worker import DocLibWorker
from src.csit_integration_v1.doclib_metadata import build_result,clean_semantic,make_semantic_extractor
from src.csit_integration_v1.pipeline import Extraction
from conftest import TestTokenValidator

TEXT=("CSIT 文件專區測試。This manual describes the Wi-Fi 7 access point FSW26 setup procedure. "*10).encode()
AUTH={"Authorization":"Bearer test-service"}

class FakeAuth:
    def headers(self):return {"Authorization":"Bearer fake-outbound"}

class FakeQdrant:
    """Interprets the exact-match filters used by the doclib writer and the deletion executor."""
    def __init__(self):self.points={}
    @staticmethod
    def _match(point,flt):return all(point["payload"].get(c.key)==c.match.value for c in flt.must)
    def create_payload_index(self,*a,**k):pass
    def upsert(self,collection_name,points,wait=True):
        for p in points:self.points[(collection_name,str(p.id))]={"collection":collection_name,"payload":p.payload}
    def delete(self,collection,points_selector,wait=True):
        for k in [k for k,p in self.points.items() if p["collection"]==collection and self._match(p,points_selector)]:del self.points[k]
    def count(self,collection,count_filter,exact=True):
        return SimpleNamespace(count=sum(1 for p in self.points.values() if p["collection"]==collection and self._match(p,count_filter)))

def request_body(content=TEXT,name="manual.txt",**over):
    body={"schemaVersion":"1.0","sourceSystem":"CSIT","eventType":"DocumentLibraryFileUploaded",
        "documentFileId":str(uuid.uuid4()),"csitJobId":str(uuid.uuid4()),"occurredAt":"2026-11-04T01:00:00Z",
        "file":{"originalFileName":name,"standardFileName":"std-"+name,"contentType":"text/plain","fileSizeBytes":len(content),
            "sha256":hashlib.sha256(content).hexdigest(),"downloadUrl":"https://csit.example/ignored"},
        "classification":{"l1":{"id":1,"name":"設備"},"l2":{"id":2,"name":"Wi-Fi"},"l3":None}}
    body.update(over);return body

@pytest.fixture(autouse=True)
def _posix_secret_mode(monkeypatch):
    if __import__("os").name=="nt": # the 0o077 secret-file permission check has no Windows equivalent
        from src.csit_integration_v1.config import Settings
        monkeypatch.setattr(Settings,"validate",lambda self:None)

@pytest.fixture
def dsettings(settings):return replace(settings,doclib_enabled=True)
@pytest.fixture
def drepo(repo,db_url):return DocLibRepository(db_url)
@pytest.fixture
def client(dsettings,repo,drepo):
    with TestClient(create_app(dsettings,repo,TestTokenValidator(),doclib=drepo)) as c:yield c
JOBS="/api/integrations/csit/v1/document-library/jobs"
DELS="/api/integrations/csit/v1/document-deletions"

# ---------- wire contract ----------
def test_request_contract_and_202_idempotency(client,drepo):
    body=request_body()
    r=client.post(JOBS,json=body,headers={**AUTH,"Idempotency-Key":body["csitJobId"]})
    assert r.status_code==202
    assert r.json()=={"csitJobId":body["csitJobId"],"kmJobId":r.json()["kmJobId"],"status":"Accepted"} and r.json()["kmJobId"].startswith("KM-DOC-")
    again=client.post(JOBS,json=body,headers={**AUTH,"Idempotency-Key":body["csitJobId"]})
    assert again.status_code==202 and again.json()["kmJobId"]==r.json()["kmJobId"]
    with drepo.connect() as c:assert c.execute("SELECT count(*) AS n FROM km_csit_doclib_jobs").fetchone()["n"]==1

def test_same_job_id_different_file_is_conflict(client):
    body=request_body();client.post(JOBS,json=body,headers=AUTH)
    other=copy.deepcopy(body);other["documentFileId"]=str(uuid.uuid4())
    assert client.post(JOBS,json=other,headers=AUTH).status_code==409

def test_idempotency_key_must_equal_job_id(client):
    body=request_body()
    assert client.post(JOBS,json=body,headers={**AUTH,"Idempotency-Key":str(uuid.uuid4())}).status_code==400

@pytest.mark.parametrize("mutate",[lambda b:b.pop("csitJobId"),lambda b:b["file"].update(sha256="zz"),lambda b:b.update(eventType="x"),
    lambda b:b["file"].update(originalFileName="../evil.txt")])
def test_invalid_requests_are_422_without_values(client,mutate):
    body=request_body();mutate(body)
    r=client.post(JOBS,json=body,headers=AUTH)
    assert r.status_code==422 and "zz" not in r.text and "evil" not in r.text

def test_auth_required_and_switch_gates_acceptance(client,dsettings,repo,drepo):
    assert client.post(JOBS,json=request_body()).status_code==401
    off=create_app(replace(dsettings,doclib_enabled=False),repo,TestTokenValidator(),doclib=drepo)
    with TestClient(off) as c:
        assert c.post(JOBS,json=request_body(),headers=AUTH).status_code==503
        assert c.post(DELS,json={},headers=AUTH).status_code==422

# ---------- Completed.result ----------
def _extraction():return Extraction(text="Wi-Fi 7 access point FSW26 manual. Setup procedure for the access point.")
def test_result_has_every_key_and_drops_invented_keywords(tmp_path):
    from datetime import datetime,timezone
    sem={"documentType":"Manual","summary":"說明 FSW26 設定","keywords":["FSW26","access point","not in document","FSW26"]}
    r=build_result({"content_type":"text/plain"},_extraction(),".pdf",tmp_path/"x.pdf",sem,"idx/1",3,datetime.now(timezone.utc))
    validate_result(r)
    assert r["document"]["documentType"]=="Manual" and r["document"]["keywords"]==["FSW26","access point"]
    assert r["document"]["authors"]==[] and r["document"]["documentDate"] is None and r["technical"]["measurements"]==[]
    assert r["indexing"]["status"]=="Completed" and r["extraction"]["ocrUsed"] is False

def test_semantic_failure_falls_back_to_nulls():
    from datetime import datetime,timezone
    import tempfile,pathlib
    extract=make_semantic_extractor(lambda p:(_ for _ in ()).throw(RuntimeError("llm down")))
    assert extract("some text") is None
    r=build_result({"content_type":"t"},_extraction(),".txt",pathlib.Path(tempfile.gettempdir())/"a.txt",None,"i",1,datetime.now(timezone.utc))
    assert r["document"]["summary"] is None and r["document"]["documentType"]=="Other" and r["warnings"]
    assert clean_semantic({"documentType":"Poem","summary":"  "},"x")=={"documentType":"Other","summary":None,"keywords":[],"zone_hint":None,"technology":None}

def test_incomplete_result_is_rejected():
    from datetime import datetime,timezone
    import pathlib
    r=build_result({"content_type":"t"},_extraction(),".txt",pathlib.Path("a.txt"),None,"i",1,datetime.now(timezone.utc))
    del r["technical"]["errorCodes"]
    with pytest.raises(ValueError):validate_result(r)

# ---------- worker end to end ----------
class Csit:
    """Fake CSIT: file download + both callback endpoints; records every callback."""
    def __init__(self,content=TEXT):
        self.content=content;self.callbacks=[];self.download_status=200;self.downloads=0
    def __call__(self,r):
        if r.method=="GET":
            assert "/document-library/files/" in r.url.path and r.url.path.endswith("/content")
            self.downloads+=1
            return httpx.Response(self.download_status,content=self.content)
        p=json.loads(r.content);self.callbacks.append((r.url.path,p));return httpx.Response(204)

def make_worker(dsettings,drepo,csit,qdrant,semantic=None):
    client=DocLibClient(dsettings,FakeAuth(),transport=httpx.MockTransport(csit))
    writer=DocLibQdrantWriter(qdrant,"docs",lambda chunks:[[.1,.2] for _ in chunks],400)
    pipeline=DocLibPipeline(dsettings,drepo,client,writer,semantic=semantic)
    executor=DeletionExecutor(drepo,dsettings.storage_root,qdrant=qdrant,doclib_collection="docs",report_collections=("reports",))
    return DocLibWorker(dsettings,drepo,client,pipeline,executor)

def submit(drepo,**kw):
    body=request_body(**kw);return body,drepo.submit(DocLibRequest.model_validate(body))
def drain_callbacks(w):
    while w.callback_one():pass

def test_ingestion_completes_with_full_metadata_and_ordered_callbacks(dsettings,drepo):
    csit,q=Csit(),FakeQdrant()
    w=make_worker(dsettings,drepo,csit,q,semantic=lambda t:{"documentType":"Manual","summary":"Wi-Fi 7 設定手冊","keywords":["FSW26","Wi-Fi 7"]})
    body,job=submit(drepo)
    assert w.process_one() and not w.process_one()
    drain_callbacks(w)
    assert [p["status"] for _,p in csit.callbacks]==["Processing","Completed"]
    assert {path for path,_ in csit.callbacks}=={"/api/integrations/km/v1/document-library/ingestion-status"}
    proc,done=csit.callbacks[0][1],csit.callbacks[1][1]
    assert proc["timestamps"]["startedAt"] and proc["result"] is None and proc["error"] is None
    assert done["callbackId"]!=proc["callbackId"] and done["csitJobId"]==body["csitJobId"] and done["kmJobId"]==job["km_job_id"]
    validate_result(done["result"])
    assert done["result"]["document"]["documentType"]=="Manual" and done["result"]["document"]["keywords"]==["FSW26","Wi-Fi 7"]
    assert done["result"]["indexing"]["chunkCount"]==len([1 for p in q.points.values()])>0
    pts=[p["payload"] for p in q.points.values()]
    assert all(p["document_file_id"]==body["documentFileId"] and p["source_type"]=="DocumentLibraryFile" for p in pts)

def test_sha256_mismatch_fails_terminally_with_no_retry_and_no_index(dsettings,drepo):
    csit,q=Csit(content=TEXT[:-1]+b"X"),FakeQdrant() # same size, different bytes
    w=make_worker(dsettings,drepo,csit,q)
    body,_=submit(drepo,content=TEXT)
    assert w.process_one();drain_callbacks(w)
    failed=csit.callbacks[-1][1]
    assert failed["status"]=="Failed" and failed["error"]["code"]=="SHA256_MISMATCH" and failed["error"]["retryable"] is False
    assert failed["timestamps"]["failedAt"] and failed["result"] is None and not q.points and not w.process_one()

def test_transient_failure_retries_without_status_regress(dsettings,drepo):
    csit,q=Csit(),FakeQdrant();csit.download_status=503
    w=make_worker(dsettings,drepo,csit,q)
    submit(drepo)
    assert w.process_one();drain_callbacks(w)
    assert [p["status"] for _,p in csit.callbacks]==["Processing"] # no Failed while a retry is pending
    csit.download_status=200
    assert w.process_one();drain_callbacks(w)
    assert [p["status"] for _,p in csit.callbacks]==["Processing","Completed"]

def test_callback_409_then_ok_is_retried(dsettings,drepo):
    csit,q=Csit(),FakeQdrant();w=make_worker(dsettings,drepo,csit,q);submit(drepo);w.process_one()
    seq=iter([409,204,204])
    w.client.http=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(next(seq))))
    assert w.callback_one() and w.callback_one() and w.callback_one()

def test_unsupported_format_fails_cleanly(dsettings,drepo):
    csit,q=Csit(),FakeQdrant();w=make_worker(dsettings,drepo,csit,q)
    submit(drepo,name="tool.exe")
    w.process_one();drain_callbacks(w)
    assert csit.callbacks[-1][1]["error"]["code"]=="UNSUPPORTED_DOCUMENT_FORMAT" and csit.downloads==0

# ---------- deletion ----------
def deletion_body(resource,**over):
    body={"schemaVersion":"1.0","sourceSystem":"CSIT","eventType":"DocumentDeletionRequested","deletionRequestId":str(uuid.uuid4()),
        "requestedAt":"2026-11-04T02:02:00Z","reasonCode":"DocumentFileDeleted","resource":resource};body.update(over);return body
def file_resource(fid):
    return {"sourceType":"DocumentLibraryFile","documentFileId":fid,"documentId":None,"version":None,"sourceEntityId":None,"applicationId":None,"recordId":None}

def test_resource_identity_rules():
    uid=str(uuid.uuid4())
    with pytest.raises(Exception):Resource.model_validate({"sourceType":"TestReport","documentId":uid,"version":0,"sourceEntityId":uid})
    with pytest.raises(Exception):Resource.model_validate({"sourceType":"VerificationApplicationAttachment","documentId":uid,"version":2,"sourceEntityId":uid})
    with pytest.raises(Exception):Resource.model_validate({"sourceType":"DocumentLibraryFile","documentFileId":uid,"documentId":uid})
    assert Resource.model_validate({"sourceType":"TestReport","documentId":uid,"version":3,"sourceEntityId":uid}).key().startswith(uid+":3:")

def test_deletion_202_idempotent_and_conflict(client):
    fid=str(uuid.uuid4());body=deletion_body(file_resource(fid))
    r=client.post(DELS,json=body,headers={**AUTH,"Idempotency-Key":body["deletionRequestId"]})
    assert r.status_code==202 and r.json()["kmDeletionJobId"].startswith("KM-DEL-") and r.json()["status"]=="Accepted"
    assert client.post(DELS,json=body,headers=AUTH).json()["kmDeletionJobId"]==r.json()["kmDeletionJobId"]
    other=copy.deepcopy(body);other["resource"]=file_resource(str(uuid.uuid4()))
    assert client.post(DELS,json=other,headers=AUTH).status_code==409

def test_verified_deletion_removes_only_the_targeted_same_name_file(dsettings,drepo):
    dsettings=replace(dsettings,outbound_scopes=dsettings.outbound_scopes+("csit.km.deletion-status.write",))      # the v1 deletion callback needs it (CSIT Runtime 8fe25c60)
    csit,q=Csit(),FakeQdrant();w=make_worker(dsettings,drepo,csit,q)
    a,_=submit(drepo,name="same.txt");b,_=submit(drepo,name="same.txt")
    w.process_one();w.process_one();drain_callbacks(w);csit.callbacks.clear()
    assert {p["payload"]["document_file_id"] for p in q.points.values()}=={a["documentFileId"],b["documentFileId"]}
    drepo.submit_deletion(DeletionRequest.model_validate(deletion_body(file_resource(a["documentFileId"]))))
    assert w.delete_one();drain_callbacks(w)
    assert {p["payload"]["document_file_id"] for p in q.points.values()}=={b["documentFileId"]}
    assert [p["status"] for _,p in csit.callbacks]==["Processing","Completed"]
    assert csit.callbacks[0][0].endswith("/document-deletion-status")
    done=csit.callbacks[-1][1];res=done["result"]
    assert res["cleanupVerified"] is True and set(res["cleanup"])==set(CLEANUP_ITEMS)
    assert res["cleanup"]["chunks"]=="Deleted" and res["cleanup"]["graphRelations"]=="NotPresent" and res["cleanup"]["storedCopies"]=="Deleted"
    assert done["resource"]["documentFileId"]==a["documentFileId"]
    assert not doclib_dir(dsettings.storage_root,drepo_job_id(drepo,a)).exists() and doclib_dir(dsettings.storage_root,drepo_job_id(drepo,b)).exists()

def drepo_job_id(drepo,body):return body["csitJobId"]

def test_unverifiable_cleanup_is_never_completed(dsettings,drepo):
    csit,q=Csit(),FakeQdrant();w=make_worker(dsettings,drepo,csit,q)
    a,_=submit(drepo);w.process_one();drain_callbacks(w);csit.callbacks.clear()
    q.delete=lambda *a,**k:None # delete silently does nothing: residue must be detected
    drepo.submit_deletion(DeletionRequest.model_validate(deletion_body(file_resource(a["documentFileId"]))))
    w.delete_one();drain_callbacks(w)
    assert all(p["status"]!="Completed" for _,p in csit.callbacks)
    with drepo.connect() as c:assert c.execute("SELECT status,last_error_code FROM km_csit_deletion_jobs").fetchone()["last_error_code"]=="CLEANUP_NOT_VERIFIED"

def test_late_ingestion_and_in_flight_job_cannot_resurrect_deleted_file(dsettings,drepo):
    csit,q=Csit(),FakeQdrant();w=make_worker(dsettings,drepo,csit,q)
    body,job=submit(drepo)
    claimed=drepo.claim("w",60)  # worker is mid-flight when the deletion arrives
    drepo.submit_deletion(DeletionRequest.model_validate(deletion_body(file_resource(body["documentFileId"]))))
    with pytest.raises(Exception):w.pipeline.run(claimed)
    assert not q.points and drepo.get_job(claimed["csit_job_id"])["status"]=="Cancelled"
    with pytest.raises(IntegrationError) as e:drepo.submit(DocLibRequest.model_validate(request_body(documentFileId=body["documentFileId"])))
    assert e.value.code=="DOCUMENT_DELETED"

def test_late_processing_callback_cannot_follow_completed(dsettings,drepo):
    csit,q=Csit(),FakeQdrant();w=make_worker(dsettings,drepo,csit,q);submit(drepo);w.process_one()
    with drepo.connect() as c:
        rows=c.execute("SELECT payload->>'status' AS s FROM km_csit_v13_callbacks ORDER BY sequence").fetchall()
    assert [r["s"] for r in rows]==["Processing","Completed"]
    assert w.claim_one_after_done() if False else not w.process_one() # a Completed job is never claimed again

def test_completed_deletion_payload_guards():
    job={"deletion_request_id":uuid.uuid4(),"km_deletion_job_id":"KM-DEL-1","resource":{},"started_at":None,"completed_at=":None}
    job.update(completed_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),failed_at=None)
    ok={"cleanupVerified":True,"verifiedAt":"2026-11-04T02:02:58Z","cleanup":{k:"Deleted" for k in CLEANUP_ITEMS}}
    build_deletion_callback(uuid.uuid4(),job,"Completed",result=ok)
    bad=copy.deepcopy(ok);bad["cleanup"]["cache"]="Unknown"
    with pytest.raises(ValueError):build_deletion_callback(uuid.uuid4(),job,"Completed",result=bad)
    bad=copy.deepcopy(ok);bad["cleanupVerified"]=False
    with pytest.raises(ValueError):build_deletion_callback(uuid.uuid4(),job,"Completed",result=bad)

# ---------- Test Report v1 stays untouched ----------
def test_v1_worker_skips_a_deleted_report_version(repo,drepo,settings,payload):
    from src.csit_integration_v1.models import IngestionRequest
    from src.csit_integration_v1.worker import Worker
    repo.submit(IngestionRequest(**payload))
    drepo.submit_deletion(DeletionRequest.model_validate(deletion_body({"sourceType":"TestReport","documentFileId":None,
        "documentId":payload["documentId"],"version":payload["version"],"sourceEntityId":str(uuid.uuid4()),"applicationId":None,"recordId":None})))
    w=Worker(settings,repo,None,SimpleNamespace(run=lambda job:pytest.fail("must not process")),tombstones=drepo)
    assert w.process_one()
    with repo.connect() as c:
        assert c.execute("SELECT phase FROM km_csit_ingestion_jobs").fetchone()["phase"]=="Deleted"
        assert c.execute("SELECT count(*) AS n FROM km_csit_callback_deliveries").fetchone()["n"]==0

def test_oversized_download_is_rejected_terminally(dsettings,drepo):
    csit,q=Csit(content=TEXT+b"more"),FakeQdrant();w=make_worker(dsettings,drepo,csit,q)
    submit(drepo,content=TEXT);w.process_one();drain_callbacks(w)
    err=csit.callbacks[-1][1]["error"]
    assert err["code"]=="FILE_TOO_LARGE" and err["retryable"] is False and not q.points
