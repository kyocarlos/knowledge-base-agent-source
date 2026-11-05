"""CSIT x AI KM spec v1.4: v2 document jobs, all formats, version replacement, metadata changes, v2 deletion."""
import copy,hashlib,io,json,uuid,zipfile
from dataclasses import replace
from types import SimpleNamespace
import httpx,pytest
from fastapi.testclient import TestClient
from src.csit_integration_v1.api import create_app
from src.csit_integration_v1.auth import ServiceIdentity
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.doclib_client import DocLibClient
from src.csit_integration_v1.doclib_deletion import DeletionExecutor
from src.csit_integration_v1.doclib_worker import DocLibWorker
from src.csit_integration_v1.doclib_models import CLEANUP_ITEMS
from src.csit_integration_v1.doclib_pipeline import DocLibPipeline,DocLibQdrantWriter
from src.csit_integration_v1.v2_models import (DocumentJobRequest,MetadataChangeRequest,V2DeletionRequest,build_job_callback,
    build_deletion_callback_v2,validate_result_v2)
from src.csit_integration_v1.v2_pipeline import V2Pipeline,V2QdrantWriter,v2_dir
from src.csit_integration_v1.v2_repository import V2Repository
from src.csit_integration_v1.v2_worker import V2Processor
from conftest import TestTokenValidator

TEXT=("CSIT 驗證申請附件。This sheet lists the Wi-Fi 7 access point FSW26 verification items. "*10).encode()
AUTH={"Authorization":"Bearer test-service"}
JOBS="/api/integrations/csit/v2/document-jobs"
CHANGES="/api/integrations/csit/v2/document-metadata-changes"
DELS="/api/integrations/csit/v2/document-deletions"
SHA=lambda b:hashlib.sha256(b).hexdigest()
EVENT={"VerificationApplicationAttachment":"VerificationApplicationAttachmentArchived","VendorFile":"VendorFileArchived","EquipmentAttachment":"EquipmentAttachmentArchived"}

class Validator:
    """Scopes by token so both the v1.3 name and the v1.4 per-endpoint names can be exercised."""
    def validate(self,token):
        scopes={"v13":{"km.ingestion.submit"},"jobs":{"km.ingestion.write"},"changes":{"km.metadata.write"},"deletions":{"km.deletion.write"},
                "other":{"unrelated.scope"}}.get(token.removeprefix("t-"))
        if scopes is None:raise AssertionError(token)
        return ServiceIdentity("csit-test",frozenset(scopes))

def auth(kind="v13"):return {"Authorization":"Bearer t-"+kind}

class FakeAuth:
    def headers(self):return {"Authorization":"Bearer fake-outbound"}

class FakeQdrant:
    def __init__(self):self.points={}
    @staticmethod
    def _match(point,flt):return all(point["payload"].get(c.key)==c.match.value for c in flt.must)
    def create_payload_index(self,*a,**k):pass
    def upsert(self,collection_name,points,wait=True):
        for p in points:self.points[(collection_name,str(p.id))]={"collection":collection_name,"payload":dict(p.payload)}
    def delete(self,collection,points_selector,wait=True):
        for k in [k for k,p in self.points.items() if p["collection"]==collection and self._match(p,points_selector)]:del self.points[k]
    def count(self,collection,count_filter,exact=True):
        return SimpleNamespace(count=sum(1 for p in self.points.values() if p["collection"]==collection and self._match(p,count_filter)))
    def set_payload(self,collection,payload,points,wait=True):
        for p in self.points.values():
            if p["collection"]==collection and self._match(p,points):p["payload"].update(payload)

def job_body(source="VerificationApplicationAttachment",content=TEXT,name="notes.txt",version=1,doc_id=None,**over):
    doc_id=doc_id or str(uuid.uuid4())
    entity=str(uuid.uuid4()) if source=="VerificationApplicationAttachment" else doc_id
    body={"schemaVersion":"2.0","eventId":str(uuid.uuid4()),"csitJobId":str(uuid.uuid4()),"eventType":EVENT[source],"sourceSystem":"CSIT",
        "source":{"type":source,"entityId":entity,"moduleCode":"verification-applications","applicationId":str(uuid.uuid4()),
                  "recordId":None,"vendorId":None,"equipmentId":None},
        "document":{"id":doc_id,"version":version,"originalFileName":name,"contentType":"application/octet-stream","sizeBytes":len(content),
            "sha256":SHA(content),"downloadUrl":"https://csit.example/ignored","archivedAt":"2026-11-05T01:07:04Z",
            "approval":{"mode":"Approved","referenceId":str(uuid.uuid4()),"approvedAt":"2026-11-05T01:06:58Z"}},
        "classification":{"l1":None,"l2":None,"l3":None},"supersedes":None,"occurredAt":"2026-11-05T01:07:04Z"}
    body.update(over);return body

@pytest.fixture(autouse=True)
def _posix_secret_mode(monkeypatch):
    if __import__("os").name=="nt":
        from src.csit_integration_v1.config import Settings
        monkeypatch.setattr(Settings,"validate",lambda self:None)

@pytest.fixture
def dsettings(settings):return replace(settings,doclib_enabled=True)
@pytest.fixture
def vrepo(repo,db_url):return V2Repository(db_url)
@pytest.fixture
def client(dsettings,repo,vrepo):
    with TestClient(create_app(dsettings,repo,Validator(),doclib=vrepo)) as c:yield c

# ---------- wire contract ----------
def test_202_idempotent_and_dto(client,vrepo):
    b=job_body()
    r=client.post(JOBS,json=b,headers={**auth(),"Idempotency-Key":b["eventId"]})
    assert r.status_code==202
    assert r.json()=={"eventId":b["eventId"],"csitJobId":b["csitJobId"],"kmJobId":r.json()["kmJobId"],"status":"Accepted"}
    assert r.json()["kmJobId"].startswith("KM-ING-")
    again=client.post(JOBS,json=b,headers=auth())
    assert again.status_code==202 and again.json()["kmJobId"]==r.json()["kmJobId"]
    with vrepo.connect() as c:assert c.execute("SELECT count(*) AS n FROM km_csit_v2_jobs").fetchone()["n"]==1

def test_same_event_id_different_file_is_conflict(client):
    b=job_body();client.post(JOBS,json=b,headers=auth())
    o=copy.deepcopy(b);o["document"]["sha256"]=SHA(b"other")
    assert client.post(JOBS,json=o,headers=auth()).status_code==409

def test_two_attachments_with_the_same_name_and_hash_are_separate_jobs(client):
    a=job_body(name="same.txt");b=job_body(name="same.txt")
    ra,rb=[client.post(JOBS,json=x,headers=auth()) for x in (a,b)]
    assert ra.status_code==rb.status_code==202 and ra.json()["kmJobId"]!=rb.json()["kmJobId"]

def test_only_one_active_canonical_job_per_source_version(client):
    a=job_body();client.post(JOBS,json=a,headers=auth())
    b=job_body(doc_id=a["document"]["id"]);b["source"]["entityId"]=a["source"]["entityId"]
    assert client.post(JOBS,json=b,headers=auth()).status_code==409

@pytest.mark.parametrize("mutate",[
    lambda b:b.update(schemaVersion="1.0"),lambda b:b.pop("eventId"),lambda b:b["document"].update(sha256="zz"),
    lambda b:b["document"].update(version=0),lambda b:b["document"].update(sizeBytes=0),lambda b:b["document"].update(originalFileName="../x.txt"),
    lambda b:b.update(eventType="VendorFileArchived"),                      # source.type disagrees
    lambda b:b["source"].update(type="Nope"),lambda b:b.update(sourceSystem="OTHER")])
def test_invalid_contract_is_400_without_values(client,mutate):
    b=job_body();mutate(b)
    r=client.post(JOBS,json=b,headers=auth())
    assert r.status_code==400 and "zz" not in r.text and "../x" not in r.text

def test_vendor_and_equipment_use_one_id_for_entity_and_document(client):
    b=job_body("VendorFile");b["source"]["entityId"]=str(uuid.uuid4())
    assert client.post(JOBS,json=b,headers=auth()).status_code==400

def test_idempotency_key_must_equal_event_id(client):
    assert client.post(JOBS,json=job_body(),headers={**auth(),"Idempotency-Key":str(uuid.uuid4())}).status_code==400

def test_non_json_content_type_is_415_and_idempotency_header_optional(client):
    assert client.post(JOBS,content=b"x",headers={**auth(),"Content-Type":"text/plain"}).status_code==415

def test_scopes_v13_name_and_v14_names_both_work_and_are_endpoint_specific(client):
    assert client.post(JOBS,json=job_body(),headers=auth("jobs")).status_code==202
    assert client.post(JOBS,json=job_body(),headers=auth("changes")).status_code==403
    assert client.post(JOBS,json=job_body(),headers=auth("other")).status_code==403
    assert client.post(JOBS,json=job_body()).status_code==401
    assert client.post(DELS,json={},headers=auth("jobs")).status_code==403
    assert client.post(CHANGES,json={},headers=auth("deletions")).status_code==403

def test_switch_gates_acceptance(dsettings,repo,vrepo):
    with TestClient(create_app(replace(dsettings,doclib_enabled=False),repo,Validator(),doclib=vrepo)) as c:
        assert c.post(JOBS,json=job_body(),headers=auth()).status_code==503

# ---------- worker end to end ----------
class Csit:
    """Fake CSIT: file download per source route + every callback endpoint."""
    def __init__(self,content=TEXT):
        self.content=content;self.callbacks=[];self.downloads=[];self.status=200;self.headers=[]
    def __call__(self,r):
        if r.method=="GET":
            self.downloads.append(r.url.path)
            return httpx.Response(self.status,content=self.content)
        p=json.loads(r.content);self.callbacks.append((r.url.path,p));self.headers.append(dict(r.headers));return httpx.Response(204)
    def statuses(self,path_end):return [p["status"] for path,p in self.callbacks if path.endswith(path_end)]

def make(dsettings,vrepo,csit,qdrant,semantic=None):
    client=DocLibClient(dsettings,FakeAuth(),transport=httpx.MockTransport(csit))
    embed=lambda chunks:[[.1,.2] for _ in chunks]
    v2writer=V2QdrantWriter(qdrant,"docs",embed,400)
    pipeline=V2Pipeline(dsettings,vrepo,client,v2writer,semantic=semantic)
    executor=DeletionExecutor(vrepo,dsettings.storage_root,qdrant=qdrant,doclib_collection="docs",report_collections=("reports",))
    proc=V2Processor(dsettings,vrepo,pipeline,v2writer,report_collections=("reports",))
    w=DocLibWorker(dsettings,vrepo,client,DocLibPipeline(dsettings,vrepo,client,DocLibQdrantWriter(qdrant,"docs",embed,400)),executor,
                   extra_steps=proc.steps())
    w.v2=proc;return w
def submit(vrepo,**kw):
    b=job_body(**kw);return b,vrepo.submit_job(DocumentJobRequest.model_validate(b))
def drain(w):
    while w.callback_one():pass

@pytest.mark.parametrize("source,route",[("VerificationApplicationAttachment","/documents/{doc}/versions/1/content"),
    ("VendorFile","/vendor-files/{doc}/content"),("EquipmentAttachment","/equipment-documents/{doc}/content")])
def test_each_source_downloads_from_its_own_route_and_completes(dsettings,vrepo,source,route):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    b,_=submit(vrepo,source=source)
    assert w.v2.ingest_one() and not w.v2.ingest_one();drain(w)
    assert csit.downloads==["/api/integrations/km/v1"+route.format(doc=b["document"]["id"])]  # the payload downloadUrl is never followed
    assert csit.statuses("/v2/document-jobs/status")==["Processing","Completed"]
    proc,done=[p for path,p in csit.callbacks]
    assert proc["result"] is None and proc["error"] is None and proc["timestamps"]["startedAt"]
    assert done["eventId"]==b["eventId"] and done["csitJobId"]==b["csitJobId"] and done["sourceType"]==source
    assert done["sourceEntityId"]==b["source"]["entityId"] and done["documentId"]==b["document"]["id"] and done["sourceSha256"]==b["document"]["sha256"]
    assert done["timestamps"]["startedAt"] and done["timestamps"]["completedAt"] and done["timestamps"]["failedAt"] is None
    validate_result_v2(done["result"])
    assert done["result"]["metadataSchemaVersion"]=="2.0" and "sourceSpecific" in done["result"] and done["result"]["indexing"]["chunkCount"]>0
    assert csit.headers[-1]["idempotency-key"]==done["callbackId"]  # spec 3.1: status callbacks carry callbackId as the key

def test_points_carry_the_exact_source_identity(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    b,_=submit(vrepo);w.v2.ingest_one()
    pts=[p["payload"] for p in q.points.values()]
    assert pts and all(p["source_entity_id"]==b["source"]["entityId"] and p["document_id"]==b["document"]["id"] and p["document_version"]==1
                       and p["source_type"]=="VerificationApplicationAttachment" and p["index_state"]=="Active" for p in pts)

# ---------- every format becomes a job; nothing is skipped ----------
def zipped(parts):
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w") as z:
        for n,c in parts.items():z.writestr(n,c)
    return buf.getvalue()
def xlsx():
    from openpyxl import Workbook
    wb=Workbook();ws=wb.active;ws.title="Sheet1";ws.append(["item","result"]);ws.append(["FSW26 throughput","ok"])
    buf=io.BytesIO();wb.save(buf);return buf.getvalue()
def pptx():
    return zipped({"[Content_Types].xml":"<x/>","ppt/presentation.xml":"<p/>",
        "ppt/slides/slide1.xml":"<p:sld><a:t>Wi-Fi 7 plan</a:t><a:t>FSW26 schedule</a:t></p:sld>","ppt/slides/slide2.xml":"<p:sld><a:t>Second slide</a:t></p:sld>"})

@pytest.mark.parametrize("name,content",[("n.txt",TEXT),("n.csv",b"a,b\n1,2\n"),("n.md",b"# Title\nFSW26 notes\n"),("n.xlsx",xlsx()),("n.pptx",pptx())])
def test_readable_formats_complete(dsettings,vrepo,name,content):
    csit,q=Csit(content),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    submit(vrepo,content=content,name=name);w.v2.ingest_one();drain(w)
    done=csit.callbacks[-1][1]
    assert done["status"]=="Completed",done
    assert done["result"]["extraction"]["sourceFormat"]==name.split(".")[-1] and done["result"]["extraction"]["extractedCharacterCount"]>0
    if name.endswith(".xlsx"):assert done["result"]["extraction"]["sheetNames"]==["Sheet1"]==done["result"]["sourceSpecific"]["sheetNames"]

def test_pptx_text_is_extracted_slide_by_slide(dsettings,vrepo):
    csit,q=Csit(pptx()),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    submit(vrepo,content=pptx(),name="deck.pptx");w.v2.ingest_one()
    text="".join(p["payload"]["content"] for p in q.points.values())
    assert text.index("Wi-Fi 7 plan")<text.index("Second slide")

@pytest.mark.parametrize("name,content,code",[
    ("photo.png",b"\x89PNG\r\n\x1a\n"+b"0"*40,"UNSUPPORTED_FORMAT"),("photo.jpg",b"\xff\xd8\xff"+b"0"*40,"UNSUPPORTED_FORMAT"),
    ("bundle.zip",zipped({"a.txt":"x"}),"UNSUPPORTED_FORMAT"),("data.weird",b"abc"*20,"UNSUPPORTED_FORMAT"),("noext",b"abc"*20,"UNSUPPORTED_FORMAT")])
def test_unreadable_formats_are_accepted_then_failed_with_a_code_never_downloaded(dsettings,vrepo,name,content,code):
    csit,q=Csit(content),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    submit(vrepo,content=content,name=name);w.v2.ingest_one();drain(w)
    failed=csit.callbacks[-1][1]
    assert csit.statuses("/status")==["Processing","Failed"] and failed["error"]["code"]==code and failed["error"]["retryable"] is False
    assert failed["result"] is None and failed["timestamps"]["failedAt"] and not q.points and csit.downloads==[]

@pytest.mark.parametrize("name,content,code",[
    ("book.xlsx",b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"+b"0"*40,"ENCRYPTED_DOCUMENT"),
    ("broken.docx",b"PK\x03\x04 not really a zip"+b"0"*40,"CORRUPT_FILE"),
    ("empty.pdf",b"%PDF-1.4 junk"+b"0"*40,"CORRUPT_FILE"),
    ("run.txt",b"MZ"+b"0"*60,"MALWARE_DETECTED")])
def test_downloaded_files_that_fail_validation_get_specific_codes(dsettings,vrepo,name,content,code):
    csit,q=Csit(content),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    submit(vrepo,content=content,name=name);w.v2.ingest_one();drain(w)
    assert csit.callbacks[-1][1]["error"]["code"]==code and not q.points

def test_sha_mismatch_and_oversize_are_terminal(dsettings,vrepo):
    csit,q=Csit(TEXT[:-1]+b"X"),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    submit(vrepo,content=TEXT);w.v2.ingest_one();drain(w)
    assert csit.callbacks[-1][1]["error"]["code"]=="SHA256_MISMATCH" and not q.points
    csit2,q2=Csit(),FakeQdrant();w2=make(replace(dsettings,max_file_size=10),vrepo,csit2,q2)
    submit(vrepo);w2.v2.ingest_one();drain(w2)
    assert csit2.callbacks[-1][1]["error"]["code"]=="FILE_TOO_LARGE" and csit2.downloads==[]

def test_transient_download_failure_retries_without_failed_callback(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();csit.status=503;w=make(dsettings,vrepo,csit,q)
    submit(vrepo);w.v2.ingest_one();drain(w)
    assert csit.statuses("/status")==["Processing"]
    csit.status=200;w.v2.ingest_one();drain(w)
    assert csit.statuses("/status")==["Processing","Completed"]

# ---------- replacing a version (spec 6.1) ----------
def test_old_index_is_retired_only_after_the_new_version_completes(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    old,_=submit(vrepo,source="VendorFile");w.v2.ingest_one();drain(w)
    new_content=TEXT+b" revised"
    sup={"oldDocumentId":old["document"]["id"],"oldVersion":1,"oldSha256":old["document"]["sha256"]}
    new,_=submit(vrepo,source="VendorFile",content=new_content,version=2,supersedes=sup)
    csit.content=new_content
    states=lambda:{p["payload"]["document_id"]:p["payload"]["index_state"] for p in q.points.values()}
    assert states()=={old["document"]["id"]:"Active"}
    w.v2.ingest_one();assert w.v2.supersede_one() and not w.v2.supersede_one()
    assert states()=={old["document"]["id"]:"Superseded",new["document"]["id"]:"Active"}
    with vrepo.connect() as c:
        rows={str(r["document_id"]):r["index_state"] for r in c.execute("SELECT document_id,index_state FROM km_csit_v2_jobs")}
    assert rows=={old["document"]["id"]:"Superseded",new["document"]["id"]:"Active"}

def test_failed_replacement_leaves_the_old_index_active(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    old,_=submit(vrepo,source="VendorFile");w.v2.ingest_one();drain(w)
    sup={"oldDocumentId":old["document"]["id"],"oldVersion":1,"oldSha256":old["document"]["sha256"]}
    submit(vrepo,source="VendorFile",content=b"MZ"+b"0"*60,name="bad.txt",version=2,supersedes=sup)
    csit.content=b"MZ"+b"0"*60;w.v2.ingest_one();assert not w.v2.supersede_one();drain(w)
    assert csit.callbacks[-1][1]["status"]=="Failed"
    assert {p["payload"]["index_state"] for p in q.points.values()}=={"Active"}

# ---------- metadata changes (spec 6.2) ----------
def change_body(job,revision=2,**over):
    b={"schemaVersion":"2.0","changeId":str(uuid.uuid4()),"sourceSystem":"CSIT","sourceType":job["source"]["type"],
       "sourceEntityId":job["source"]["entityId"],"documentId":job["document"]["id"],"version":job["document"]["version"],
       "sourceRevision":revision,"occurredAt":"2026-11-05T02:00:00Z",
       "classification":{"l1":{"id":str(uuid.uuid4()),"name":"技術文件"},"l2":None,"l3":None},
       "attributes":{"tags":["wifi"],"keywords":[],"displayName":"RF Guide","modelNumbers":[],"vendorReference":None},
       "changedFields":["classification","attributes.tags"]};b.update(over);return b

def test_change_intake_rules(client,vrepo,dsettings):
    job=job_body("VendorFile");client.post(JOBS,json=job,headers=auth())
    b=change_body(job)
    r=client.post(CHANGES,json=b,headers={**auth("changes"),"Idempotency-Key":b["changeId"]})
    assert r.status_code==202 and r.json()["kmChangeJobId"].startswith("KM-CHANGE-") and r.json()["status"]=="Accepted"
    assert client.post(CHANGES,json=b,headers=auth()).json()["kmChangeJobId"]==r.json()["kmChangeJobId"]
    assert client.post(CHANGES,json=change_body(job,revision=2),headers=auth()).status_code==409   # not newer
    assert client.post(CHANGES,json=change_body(job,revision=1),headers=auth()).status_code==409   # older
    assert client.post(CHANGES,json=change_body(job,revision=3),headers=auth()).status_code==202
    ghost=job_body("VendorFile")
    assert client.post(CHANGES,json=change_body(ghost),headers=auth()).status_code==404
    bad=change_body(job,revision=9);bad["sourceRevision"]=0
    assert client.post(CHANGES,json=bad,headers=auth()).status_code==400

def test_change_updates_the_index_filters_and_reports_the_applied_revision(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    job,_=submit(vrepo,source="VendorFile");w.v2.ingest_one();drain(w);csit.callbacks.clear()
    vrepo.submit_change(MetadataChangeRequest.model_validate(change_body(job,revision=2)))
    assert w.v2.change_one() and not w.v2.change_one();drain(w)
    assert len(csit.downloads)==1  # only the original download: a change never fetches the file again
    pts=[p["payload"] for p in q.points.values()]
    assert all(p["tags"]==["wifi"] and p["classification"]["l1"]=="技術文件" and p["display_name"]=="RF Guide" and p["source_revision"]==2 for p in pts)
    assert csit.statuses("/document-metadata-changes/status")==["Processing","Completed"]
    done=csit.callbacks[-1][1]
    assert done["appliedRevision"]==2 and done["error"] is None and done["timestamps"]["completedAt"] and csit.callbacks[0][1]["appliedRevision"] is None

def test_change_waits_for_a_running_ingestion_and_fails_cleanly_when_nothing_was_indexed(dsettings,vrepo):
    csit,q=Csit(b"x"*30),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    job,_=submit(vrepo,source="VendorFile",content=b"x"*30,name="pic.png")
    vrepo.submit_change(MetadataChangeRequest.model_validate(change_body(job)))
    assert not w.v2.change_one()           # the job is still Accepted: no change is applied yet
    w.v2.ingest_one();assert w.v2.change_one();drain(w)   # job Failed -> nothing to update
    last=csit.callbacks[-1][1]
    assert last["status"]=="Failed" and last["error"]["code"]=="TARGET_NOT_INDEXED"

def test_changes_apply_in_revision_order(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    job,_=submit(vrepo,source="VendorFile");w.v2.ingest_one();drain(w);csit.callbacks.clear()
    for rev,tag in ((2,"first"),(3,"second")):
        b=change_body(job,revision=rev);b["attributes"]["tags"]=[tag];vrepo.submit_change(MetadataChangeRequest.model_validate(b))
    w.v2.change_one();w.v2.change_one();drain(w)
    assert {p["payload"]["tags"][0] for p in q.points.values()}=={"second"}
    assert [p["appliedRevision"] for _,p in csit.callbacks if p["status"]=="Completed"]==[2,3]

def test_metadata_set_during_ingestion_is_in_the_new_index(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    job,_=submit(vrepo,source="VendorFile");w.v2.ingest_one()
    vrepo.submit_change(MetadataChangeRequest.model_validate(change_body(job)));w.v2.change_one()
    with vrepo.connect() as c:assert c.execute("SELECT metadata_overrides FROM km_csit_v2_jobs").fetchone()["metadata_overrides"]["tags"]==["wifi"]
    # a re-ingest of the same version (e.g. retry after a lost lease) keeps the filter values
    row=vrepo.get_job(uuid.UUID(job["eventId"]))
    assert vrepo.overrides_job(row)["tags"]==["wifi"]

# ---------- deletion (spec 7) ----------
def del_body(job,**over):
    r={"sourceType":job["source"]["type"],"sourceEntityId":job["source"]["entityId"],"documentId":job["document"]["id"],"version":job["document"]["version"],
       "sha256":job["document"]["sha256"],"applicationId":None,"recordId":None,"vendorId":str(uuid.uuid4()),"equipmentId":None,
       "canonicalIngestionEventId":job["eventId"],"scope":"DocumentVersion"}
    b={"schemaVersion":"2.0","sourceSystem":"CSIT","eventType":"DocumentDeletionRequested","deletionRequestId":str(uuid.uuid4()),
       "requestedAt":"2026-11-05T03:00:00Z","reasonCode":"SourceDeleted","resource":r};b.update(over);return b

def test_v2_deletion_intake(client):
    job=job_body("VendorFile");client.post(JOBS,json=job,headers=auth())
    b=del_body(job)
    r=client.post(DELS,json=b,headers={**auth("deletions"),"Idempotency-Key":b["deletionRequestId"]})
    assert r.status_code==202 and r.json()["kmDeletionJobId"].startswith("KM-DEL-") and r.json()["status"]=="Accepted"
    assert client.post(DELS,json=b,headers=auth()).json()["kmDeletionJobId"]==r.json()["kmDeletionJobId"]
    other=copy.deepcopy(b);other["resource"]["version"]=2
    assert client.post(DELS,json=other,headers=auth()).status_code==409
    assert client.post(DELS,json=del_body(job,eventType="x"),headers=auth()).status_code==400
    for bad in ({"scope":"All"},{"sha256":"zz"},{"version":0}):
        x=del_body(job);x["resource"].update(bad);assert client.post(DELS,json=x,headers=auth()).status_code==400

def test_deletion_of_the_wrong_version_or_event_is_refused(client):
    job=job_body("EquipmentAttachment");client.post(JOBS,json=job,headers=auth())
    x=del_body(job);x["resource"]["sha256"]=SHA(b"another file")
    assert client.post(DELS,json=x,headers=auth()).status_code==409
    y=del_body(job);y["resource"]["canonicalIngestionEventId"]=str(uuid.uuid4())
    assert client.post(DELS,json=y,headers=auth()).status_code==409

@pytest.mark.parametrize("source",["VendorFile","EquipmentAttachment","VerificationApplicationAttachment"])
def test_verified_v2_deletion_removes_exactly_that_version(dsettings,vrepo,source):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    a,_=submit(vrepo,source=source,name="same.txt");b,_=submit(vrepo,source=source,name="same.txt")
    w.v2.ingest_one();w.v2.ingest_one();drain(w);csit.callbacks.clear()
    req=V2DeletionRequest.model_validate(del_body(a));vrepo.submit_deletion_v2(req)
    assert w.delete_one() and not w.delete_one();drain(w)
    assert {p["payload"]["document_id"] for p in q.points.values()}=={b["document"]["id"]}
    assert csit.statuses("/v2/document-deletions/status")==["Processing","Completed"]
    done=csit.callbacks[-1][1]
    assert done["schemaVersion"]=="2.0" and done["resource"]==req.resource.wire() and done["timestamps"]["startedAt"] and done["timestamps"]["completedAt"]
    res=done["result"]
    assert res["cleanupVerified"] is True and set(res["cleanup"])==set(CLEANUP_ITEMS)
    assert res["cleanup"]["chunks"]=="Deleted" and res["cleanup"]["graphRelations"]=="NotPresent" and res["cleanup"]["storedCopies"]=="Deleted"
    assert not v2_dir(dsettings.storage_root,a["eventId"]).exists() and v2_dir(dsettings.storage_root,b["eventId"]).exists()
    with vrepo.connect() as c:
        row=c.execute("SELECT status,result_json,request_payload FROM km_csit_v2_jobs WHERE event_id=%s",(a["eventId"],)).fetchone()
    assert row["status"]=="Deleted" and row["result_json"] is None and row["request_payload"]=={}

def test_deleted_version_cannot_be_ingested_or_changed_again(dsettings,vrepo,client):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    a,_=submit(vrepo,source="VendorFile");w.v2.ingest_one()
    vrepo.submit_deletion_v2(V2DeletionRequest.model_validate(del_body(a)))
    late=copy.deepcopy(a);late["eventId"]=str(uuid.uuid4())
    assert client.post(JOBS,json=late,headers=auth()).status_code==410
    assert client.post(CHANGES,json=change_body(a),headers=auth()).status_code==410

def test_in_flight_job_is_cancelled_by_a_deletion(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    a,_=submit(vrepo,source="VendorFile")
    claimed=vrepo.claim_job("w",60)
    vrepo.submit_deletion_v2(V2DeletionRequest.model_validate(del_body(a)))
    with pytest.raises(Exception):w.v2.pipeline.run(claimed)
    assert not q.points and vrepo.get_job(uuid.UUID(a["eventId"]))["status"]=="Cancelled"

def test_v1_verification_deletion_also_cleans_v2_data(dsettings,vrepo):
    """Spec 7.1: the v1 deletion route stays valid for verification attachments, which v1.4 ingests through v2."""
    from src.csit_integration_v1.doclib_models import DeletionRequest
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    a,_=submit(vrepo);w.v2.ingest_one();drain(w);csit.callbacks.clear()
    vrepo.submit_deletion(DeletionRequest.model_validate({"schemaVersion":"1.0","sourceSystem":"CSIT","eventType":"DocumentDeletionRequested",
        "deletionRequestId":str(uuid.uuid4()),"requestedAt":"2026-11-05T03:00:00Z","reasonCode":"DocumentFileDeleted",
        "resource":{"sourceType":"VerificationApplicationAttachment","documentFileId":None,"documentId":a["document"]["id"],"version":1,
                    "sourceEntityId":a["source"]["entityId"],"applicationId":None,"recordId":None}}))
    w.delete_one();drain(w)
    assert not q.points and csit.callbacks[-1][0].endswith("/km/v1/document-deletion-status") and csit.callbacks[-1][1]["status"]=="Completed"

def test_unverifiable_v2_cleanup_is_never_completed(dsettings,vrepo):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    a,_=submit(vrepo,source="VendorFile");w.v2.ingest_one();drain(w);csit.callbacks.clear()
    q.delete=lambda *x,**k:None
    vrepo.submit_deletion_v2(V2DeletionRequest.model_validate(del_body(a)));w.delete_one();drain(w)
    assert all(p["status"]!="Completed" for _,p in csit.callbacks)

# ---------- callback guards ----------
def test_failed_callback_needs_an_error_and_completed_needs_a_valid_result():
    import datetime
    now=datetime.datetime.now(datetime.timezone.utc)
    job={"event_id":uuid.uuid4(),"csit_job_id":uuid.uuid4(),"km_job_id":"KM-ING-1","source_type":"VendorFile","source_entity_id":uuid.uuid4(),
         "document_id":uuid.uuid4(),"version":1,"expected_sha256":"a"*64,"started_at":now,"completed_at":now,"failed_at":now}
    with pytest.raises(ValueError):build_job_callback(uuid.uuid4(),job,"Failed")
    with pytest.raises(ValueError):build_job_callback(uuid.uuid4(),job,"Completed",result={"metadataSchemaVersion":"2.0"})
    p=build_job_callback(uuid.uuid4(),job,"Failed",error=IntegrationError("ENCRYPTED_DOCUMENT","pw",False))
    assert p["result"] is None and p["error"]=={"code":"ENCRYPTED_DOCUMENT","message":"pw","retryable":False}
    assert p["timestamps"]=={"startedAt":p["timestamps"]["startedAt"],"completedAt":None,"failedAt":p["timestamps"]["failedAt"]}

def test_v2_result_requires_source_specific_and_accepts_new_methods():
    from src.csit_integration_v1.v2_pipeline import build_result_v2
    from src.csit_integration_v1.pipeline import Extraction
    from datetime import datetime,timezone
    import pathlib
    job={"source_type":"EquipmentAttachment"}
    r=build_result_v2(job,Extraction(text="FSW26 specification text. "*5),".txt",pathlib.Path("a.txt"),None,"i",1,datetime.now(timezone.utc))
    assert r["sourceSpecific"]=={"specifications":[],"capabilitySummary":None,"limitations":[]}
    for m in ("Visual","None"):
        x=copy.deepcopy(r);x["extraction"]["method"]=m;validate_result_v2(x)
    del r["sourceSpecific"]
    with pytest.raises(ValueError):validate_result_v2(r)

def test_deletion_callback_v2_guards():
    import datetime
    now=datetime.datetime.now(datetime.timezone.utc)
    job={"deletion_request_id":uuid.uuid4(),"km_deletion_job_id":"KM-DEL-1","resource":{},"started_at":now,"completed_at":now,"failed_at":None}
    ok={"cleanupVerified":True,"verifiedAt":"2026-11-05T03:00:58Z","cleanup":{k:"Deleted" for k in CLEANUP_ITEMS}}
    build_deletion_callback_v2(uuid.uuid4(),job,"Completed",result=ok)
    bad=copy.deepcopy(ok);bad["cleanup"]["cache"]="Pending"
    with pytest.raises(ValueError):build_deletion_callback_v2(uuid.uuid4(),job,"Completed",result=bad)

# ---------- configuration ----------
def test_analysis_results_are_off_unless_configured_and_outbound_scopes_default_to_v13(dsettings):
    assert dsettings.analysis_source_entity=="" and dsettings.outbound_scopes==("csit.document.read","csit.ingestion.status.write")
    from src.csit_integration_v1.config import Settings
    import os
    os.environ["KM_CSIT_OUTBOUND_SCOPES"]="csit.documents.read,csit.km.status.write,csit.km.deletion-status.write"
    try:assert Settings.from_env().outbound_scopes==("csit.documents.read","csit.km.status.write","csit.km.deletion-status.write")
    finally:del os.environ["KM_CSIT_OUTBOUND_SCOPES"]
    steps=[l for _,l in V2Processor(dsettings,None,None,None).steps()]
    assert "v2-analysis" not in steps
    assert "v2-analysis" in [l for _,l in V2Processor(replace(dsettings,analysis_source_entity="documentId"),None,None,None).steps()]
