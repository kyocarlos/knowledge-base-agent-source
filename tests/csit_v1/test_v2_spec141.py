"""CSIT x AI KM spec v1.4.1 (Anderson 11 answers): closed event types and reason codes, 409 policy, empty extraction, Correlation Resolver."""
import json,uuid
from dataclasses import replace
import httpx,pytest
from psycopg.types.json import Jsonb
from src.csit_integration_v1.doclib_client import DocLibClient
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.models import IngestionRequest
from src.csit_integration_v1.v2_models import DocumentJobRequest
from src.csit_integration_v1.v2_worker import V2Processor
from test_v2_spec14 import (job_body,make,submit,drain,Csit,FakeQdrant,FakeAuth,auth,JOBS,DELS,SHA,TEXT,del_body,dsettings,vrepo,client,
                            _posix_secret_mode)

# ---------- event types (answer 5) ----------
def replacement(source,**over):
    b=job_body("VendorFile",**over)
    ev={"TestReport":"TestReportCommitted","DocumentLibraryFile":"DocumentLibraryFileUploaded"}[source]
    b["eventType"]=ev;b["source"]["type"]=source
    if source=="DocumentLibraryFile":b["source"]["entityId"]=b["document"]["id"]
    else:b["source"]["entityId"]=str(uuid.uuid4())      # ModuleCaseFile.Id is not the document id
    b["supersedes"]={"oldDocumentId":str(uuid.uuid4()),"oldVersion":1,"oldSha256":SHA(b"old")}
    b["document"]["version"]=2
    return b

@pytest.mark.parametrize("source",["TestReport","DocumentLibraryFile"])
def test_existing_v1_event_names_are_accepted_on_v2_only_as_replacements(client,source):
    b=replacement(source)
    r=client.post(JOBS,json=b,headers=auth("jobs"))
    assert r.status_code==202,r.text
    bare=replacement(source);bare["supersedes"]=None
    assert client.post(JOBS,json=bare,headers=auth()).status_code==400                       # a first delivery stays on v1

def test_event_and_source_must_agree_and_testreport_ids_stay_apart(client):
    b=replacement("TestReport");b["eventType"]="DocumentLibraryFileUploaded"
    assert client.post(JOBS,json=b,headers=auth()).status_code==400
    ok=replacement("TestReport");assert ok["source"]["entityId"]!=ok["document"]["id"]
    assert client.post(JOBS,json=ok,headers=auth()).status_code==202
    d=replacement("DocumentLibraryFile");d["source"]["entityId"]=str(uuid.uuid4())
    assert client.post(JOBS,json=d,headers=auth()).status_code==400                          # a library file has one id
    assert client.post(JOBS,json={**job_body(),"eventType":"SomethingElse"},headers=auth()).status_code==400

def test_a_source_version_is_never_delivered_through_both_routes(client,repo,payload):
    repo.submit(IngestionRequest(**payload))
    b=replacement("TestReport");b["document"]["id"]=payload["documentId"];b["document"]["version"]=payload["version"]
    r=client.post(JOBS,json=b,headers=auth());assert r.status_code==409 and r.json()["detail"]["code"]=="V1_JOB_EXISTS"
    other=replacement("TestReport");assert client.post(JOBS,json=other,headers=auth()).status_code==202

def test_replacing_a_v1_test_report_marks_its_report_points_superseded(dsettings,vrepo):
    from src.csit_integration_v1.v2_pipeline import V2QdrantWriter
    q=FakeQdrant()
    old_doc=str(uuid.uuid4())
    q.points[("reports","p1")]={"collection":"reports","payload":{"document_id":old_doc,"document_version":1,"content":"x"}}
    w=V2QdrantWriter(q,"docs",lambda c:[],400,extra_collections=("reports",))
    w.set_state(old_doc,1,"a"*64,"Superseded")
    assert q.points[("reports","p1")]["payload"]["index_state"]=="Superseded"

def test_report_points_are_retired_even_when_the_report_collection_is_the_library_collection(dsettings,vrepo):
    from src.csit_integration_v1.v2_pipeline import V2QdrantWriter
    q=FakeQdrant();old_doc=str(uuid.uuid4())
    q.points[("docs","p1")]={"collection":"docs","payload":{"document_id":old_doc,"document_version":1,"content":"x"}}   # written by the v1 pipeline: no sha256
    q.points[("docs","p2")]={"collection":"docs","payload":{"document_id":str(uuid.uuid4()),"document_version":1,"content":"y"}}
    w=V2QdrantWriter(q,"docs",lambda c:[],400,extra_collections=("docs",))
    w.set_state(old_doc,1,"a"*64,"Superseded")
    assert q.points[("docs","p1")]["payload"]["index_state"]=="Superseded" and "index_state" not in q.points[("docs","p2")]["payload"]

# ---------- reason codes (answer 9) ----------
@pytest.mark.parametrize("reason",["sourcedeleted","DocumentFileDeleted","TestReportVersionDeleted","Other","","SourceDeleted "[:-1]+"x"])
def test_v2_deletion_reason_code_is_a_closed_case_sensitive_enum(client,reason):
    job=job_body("VendorFile");client.post(JOBS,json=job,headers=auth())
    r=client.post(DELS,json=del_body(job,reasonCode=reason),headers=auth())
    assert r.status_code==400

@pytest.mark.parametrize("reason",["SourceDeleted","VersionSuperseded","AdministrativeCleanup"])
def test_v2_deletion_accepts_the_three_codes(client,reason):
    job=job_body("VendorFile");client.post(JOBS,json=job,headers=auth())
    assert client.post(DELS,json=del_body(job,reasonCode=reason),headers=auth()).status_code==202

# ---------- nothing is Completed without an index (answers 6, 7, 10) ----------
@pytest.mark.parametrize("content,name",[(b"   \n\t  \n",  "blank.txt"),(b"\n",  "newline.md")])
def test_a_file_with_no_extractable_text_is_failed_not_completed(dsettings,vrepo,content,name):
    csit,q=Csit(content),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    submit(vrepo,content=content,name=name);w.v2.ingest_one();drain(w)
    last=csit.callbacks[-1][1]
    assert last["status"]=="Failed" and last["error"]["code"]=="EMPTY_EXTRACTION" and last["error"]["retryable"] is False and not q.points

@pytest.mark.parametrize("name,content",[("p.png",b"\x89PNG\r\n\x1a\n"+b"0"*40),("a.zip",b"PK\x03\x04"+b"0"*40),("x.unknown",b"abc"*20)])
def test_unsupported_formats_are_failed_unsupported_format_never_retryable(dsettings,vrepo,name,content):
    csit,q=Csit(content),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    submit(vrepo,content=content,name=name);w.v2.ingest_one();drain(w)
    err=csit.callbacks[-1][1]["error"]
    assert err=={"code":"UNSUPPORTED_FORMAT","message":err["message"],"retryable":False} and "method" not in csit.callbacks[-1][1]

def test_every_failure_code_of_answer_8_is_non_retryable(dsettings,vrepo):
    for name,content,code in (("a.xlsx",b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"+b"0"*40,"ENCRYPTED_DOCUMENT"),("a.docx",b"PK\x03\x04bad"+b"0"*40,"CORRUPT_FILE"),
                              ("a.txt",b"MZ"+b"0"*60,"MALWARE_DETECTED")):
        csit,q=Csit(content),FakeQdrant();w=make(dsettings,vrepo,csit,q)
        submit(vrepo,content=content,name=name);w.v2.ingest_one();drain(w)
        e=csit.callbacks[-1][1]["error"];assert e["code"]==code and e["retryable"] is False
    csit,q=Csit(TEXT[:-1]+b"X"),FakeQdrant();w=make(dsettings,vrepo,csit,q)
    submit(vrepo,content=TEXT);w.v2.ingest_one();drain(w)
    e=csit.callbacks[-1][1]["error"];assert e["code"]=="SHA256_MISMATCH" and e["retryable"] is False

# ---------- 409 policy (answer 11) ----------
class StatusCsit:
    def __init__(self,answers):self.answers=list(answers);self.posts=[]
    def __call__(self,r):
        self.posts.append((r.url.path,dict(r.headers)));a=self.answers.pop(0) if self.answers else (204,"")
        return httpx.Response(a[0],text=a[1])

def post(dsettings,kind,answers,payload=None):
    csit=StatusCsit(answers)
    c=DocLibClient(dsettings,FakeAuth(),transport=httpx.MockTransport(csit))
    err=None
    try:c.post_status(kind,payload or {"callbackId":str(uuid.uuid4()),"status":"Completed"})
    except IntegrationError as e:err=e
    return err,csit

@pytest.mark.parametrize("kind",["ingestion2","change","deletion2","analysis"])
def test_a_409_on_a_v2_callback_is_not_retried(dsettings,kind):
    err,csit=post(dsettings,kind,[(409,"conflict")])
    assert err.code=="CSIT_CALLBACK_CONFLICT" and err.retryable is False

def test_only_analysis_job_not_completed_is_retried_on_409(dsettings):
    for body in ('{"code":"job_not_completed"}','job_not_completed','{"error":"JOB_NOT_COMPLETED"}'):
        err,_=post(dsettings,"analysis",[(409,body)]);assert err.code=="CSIT_ANALYSIS_JOB_NOT_COMPLETED" and err.retryable is True
    assert post(dsettings,"analysis",[(409,'{"code":"sha_mismatch"}')])[0].retryable is False
    assert post(dsettings,"ingestion2",[(409,"job_not_completed")])[0].retryable is False      # the exception is for analysis-results only

def test_v1_callbacks_keep_their_old_409_behaviour_and_transient_errors_still_retry(dsettings):
    assert post(dsettings,"ingestion",[(409,"x")])[0].retryable is True
    assert post(dsettings,"deletion",[(409,"x")])[0].retryable is True
    for code in (429,500,503):assert post(dsettings,"ingestion2",[(code,"")])[0].retryable is True
    assert post(dsettings,"ingestion2",[(401,"")])[0].retryable is False
    assert post(dsettings,"ingestion2",[(204,"")])[0] is None

def test_a_refused_callback_is_failed_after_one_attempt_and_logs_the_ids(dsettings,vrepo,caplog):
    csit,q=Csit(),FakeQdrant();w=make(dsettings,vrepo,csit,q);submit(vrepo)
    w.v2.ingest_one()
    w.client.http=httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(409,text="conflict")))
    import logging
    with caplog.at_level(logging.WARNING,logger="km.csit.doclib"):
        while w.callback_one():pass
    with vrepo.connect() as c:
        rows=c.execute("SELECT status,attempt_count,last_error_code FROM km_csit_v13_callbacks ORDER BY sequence").fetchall()
    # the first callback is refused once and ends Failed; ordering then holds the later one behind it only while it is Pending/Delivering
    assert rows[0]["status"]=="Failed" and rows[0]["attempt_count"]==1 and rows[0]["last_error_code"]=="CSIT_CALLBACK_CONFLICT"
    logged=[r.getMessage() for r in caplog.records if "CSIT_CALLBACK_CONFLICT" in r.getMessage()]
    assert logged and "eventId" in logged[0] and "kmJobId" in logged[0]

# ---------- scopes (answer 4) ----------
def test_official_v2_scopes_are_accepted_inbound_and_v1_scope_still_works(client):
    assert client.post(JOBS,json=job_body(),headers=auth("jobs")).status_code==202
    assert client.post(JOBS,json=job_body(),headers=auth("v13")).status_code==202
    assert client.post(JOBS,json=job_body(),headers=auth("deletions")).status_code==403

def test_outbound_scopes_default_to_v13_until_both_sides_switch(dsettings):
    assert dsettings.outbound_scopes==("csit.document.read","csit.ingestion.status.write")
    import os
    from src.csit_integration_v1.config import Settings
    os.environ["KM_CSIT_OUTBOUND_SCOPES"]="csit.document.read,csit.km.status.write,csit.km.deletion-status.write"
    try:assert Settings.from_env().outbound_scopes==("csit.document.read","csit.km.status.write","csit.km.deletion-status.write")
    finally:del os.environ["KM_CSIT_OUTBOUND_SCOPES"]

# ---------- Test Report analysis-results through the Correlation Resolver (answers 1, 2; C.2) ----------
SOURCE_ENTITY=str(uuid.uuid4());OUTBOX_ID=str(uuid.uuid4())

class Resolver:
    """Fake CSIT: the Correlation Resolver GET and the analysis-results POST."""
    def __init__(self,job,sha):
        self.job,self.sha=job,sha;self.gets=[];self.posts=[];self.answers=[];self.post_answers=[]
    def body(self,**over):
        j=self.job
        b={"schemaVersion":"2.0","sourceSystem":"CSIT","sourceType":"TestReport","eventId":j["event_id"],"sourceEntityId":SOURCE_ENTITY,
           "documentId":j["document_id"],"version":j["version"],"csitJobId":OUTBOX_ID,"kmJobId":str(j["job_id"]),"sourceSha256":self.sha,"status":"Completed"}
        b.update(over);return b
    def __call__(self,r):
        if r.method=="GET":
            self.gets.append((r.url.path,dict(r.url.params)))
            a=self.answers.pop(0) if self.answers else (200,self.body())
            return httpx.Response(a[0],json=a[1] if isinstance(a[1],(dict,list)) else None,text=a[1] if isinstance(a[1],str) else None)
        self.posts.append((r.url.path,json.loads(r.content),dict(r.headers)))
        a=self.post_answers.pop(0) if self.post_answers else (204,"")
        return httpx.Response(a[0],text=a[1])

@pytest.fixture
def report(repo,payload,tmp_path):
    job=repo.submit(IngestionRequest(**payload))
    art=tmp_path/"normalized.json";art.write_text(json.dumps({"extraction":{"text":"Wi-Fi 7 throughput test report for FSW26. "*8}}),encoding="utf-8")
    sha=SHA(b"report bytes")
    with repo.connect() as c:
        c.execute("""UPDATE km_csit_ingestion_jobs SET status='Completed',content_sha256=%s,storage_references=%s,completed_at=clock_timestamp()
                     WHERE job_id=%s""",(sha,Jsonb({"Storage":{"artifact":str(art)},"Qdrant":{"pointIds":["a","b"]}}),job["job_id"]))
        c.execute("INSERT INTO km_csit_callback_deliveries(delivery_id,job_id,payload,status) VALUES(%s,%s,%s,'Delivered')",
                  (uuid.uuid4(),job["job_id"],Jsonb({"status":"Completed"})))
    return repo.get(job["job_id"]),sha

def processor(dsettings,vrepo,resolver,**kw):
    s=replace(dsettings,analysis_results_enabled=True,callback_retry_delays=(0,0),**kw)
    client=DocLibClient(s,FakeAuth(),transport=httpx.MockTransport(resolver))
    return V2Processor(s,vrepo,None,None,client=client),client

def queued(vrepo):
    with vrepo.connect() as c:return c.execute("SELECT * FROM km_csit_v13_callbacks WHERE kind='analysis'").fetchall()
def analysis_row(vrepo):
    with vrepo.connect() as c:return c.execute("SELECT * FROM km_csit_v2_analysis").fetchone()

def test_analysis_result_uses_the_ids_csit_resolved_not_guessed_ones(dsettings,vrepo,report):
    job,sha=report;res=Resolver(job,sha);p,client=processor(dsettings,vrepo,res)
    assert p.analysis_one() and not p.analysis_one()                                             # once only
    path,params=res.gets[0]
    assert path.endswith("/api/integrations/km/v2/test-report-correlations/"+job["event_id"])
    assert params=={"documentId":job["document_id"],"version":str(job["version"]),"kmJobId":str(job["job_id"])}
    [row]=queued(vrepo);pl=row["payload"]
    assert pl["sourceEntityId"]==SOURCE_ENTITY and pl["sourceEntityId"]!=job["document_id"]
    assert pl["csitJobId"]==OUTBOX_ID and pl["csitJobId"]!=job["event_id"]
    assert pl["sourceSha256"]==sha and pl["kmJobId"]==str(job["job_id"]) and pl["documentId"]==job["document_id"] and pl["sourceType"]=="TestReport"
    assert pl["result"]["metadataSchemaVersion"]=="2.0" and pl["result"]["document"]["documentType"]=="TestReport" and isinstance(pl["result"]["sourceSpecific"],dict)
    assert pl["supersedesAnalysisResultId"] is None and analysis_row(vrepo)["status"]=="Queued"

def test_the_analysis_result_is_posted_to_v2_analysis_results_with_the_callback_id_as_key(dsettings,vrepo,report):
    job,sha=report;res=Resolver(job,sha);p,client=processor(dsettings,vrepo,res);p.analysis_one()
    from src.csit_integration_v1.doclib_worker import DocLibWorker
    w=DocLibWorker(dsettings,vrepo,client,None,None)
    assert w.callback_one()
    path,body,headers=res.posts[0]
    assert path=="/api/integrations/km/v2/analysis-results" and headers["idempotency-key"]==body["callbackId"]

def test_nothing_is_resolved_before_csit_acknowledged_the_v1_completed_status(dsettings,vrepo,report,repo):
    job,sha=report
    with repo.connect() as c:c.execute("UPDATE km_csit_callback_deliveries SET status='Pending'")
    res=Resolver(job,sha);p,_=processor(dsettings,vrepo,res)
    assert not p.analysis_one() and res.gets==[] and queued(vrepo)==[]

@pytest.mark.parametrize("answer,code",[((404,{"error":"x"}),"CORRELATION_NOT_FOUND"),((409,{"error":"x"}),"CORRELATION_MISMATCH"),
                                        ((410,{"error":"x"}),"DOCUMENT_DELETED"),((401,{"error":"x"}),"CSIT_AUTH_FORBIDDEN"),((403,{"error":"x"}),"CSIT_AUTH_FORBIDDEN")])
def test_a_resolver_refusal_ends_the_attempt_and_sends_nothing(dsettings,vrepo,report,answer,code):
    job,sha=report;res=Resolver(job,sha);res.answers=[answer]
    p,_=processor(dsettings,vrepo,res);assert p.analysis_one() and not p.analysis_one()
    row=analysis_row(vrepo);assert row["status"]=="Skipped" and row["last_error_code"]==code and queued(vrepo)==[] and len(res.gets)==1

def test_a_temporary_resolver_failure_backs_off_then_succeeds_or_gives_up(dsettings,vrepo,report):
    job,sha=report;res=Resolver(job,sha);res.answers=[(503,"down"),(429,"slow")]
    p,_=processor(dsettings,vrepo,res)
    assert p.analysis_one() and analysis_row(vrepo)["status"]=="Pending"
    assert p.analysis_one() and analysis_row(vrepo)["attempt_count"]==2
    assert p.analysis_one() and analysis_row(vrepo)["status"]=="Queued" and len(queued(vrepo))==1
    res2=Resolver(job,sha);res2.answers=[(503,"")]*5
    with vrepo.connect() as c:c.execute("DELETE FROM km_csit_v13_callbacks WHERE kind='analysis'");c.execute("DELETE FROM km_csit_v2_analysis")
    p2,_=processor(dsettings,vrepo,res2)
    for _ in range(4):p2.analysis_one()
    assert analysis_row(vrepo)["status"]=="Skipped" and queued(vrepo)==[]                         # bounded, then recorded

@pytest.mark.parametrize("over",[{"kmJobId":"KM-OTHER"},{"eventId":str(uuid.uuid4())},{"documentId":str(uuid.uuid4())},{"version":99},{"status":"Accepted"},
    {"sourceType":"VendorFile"},{"schemaVersion":"1.0"},{"sourceEntityId":"nope"},{"csitJobId":None},{"sourceSha256":"zz"}])
def test_a_resolver_answer_that_does_not_repeat_the_request_is_never_used(dsettings,vrepo,report,over):
    job,sha=report;res=Resolver(job,sha);res.answers=[(200,res.body(**over))]
    p,_=processor(dsettings,vrepo,res);p.analysis_one()
    assert queued(vrepo)==[] and analysis_row(vrepo)["status"]=="Skipped" and analysis_row(vrepo)["last_error_code"]=="CORRELATION_INVALID"

def test_a_source_hash_that_differs_from_the_downloaded_file_is_not_sent(dsettings,vrepo,report):
    job,sha=report;res=Resolver(job,sha);res.answers=[(200,res.body(sourceSha256=SHA(b"another file")))]
    p,_=processor(dsettings,vrepo,res);p.analysis_one()
    assert queued(vrepo)==[] and analysis_row(vrepo)["last_error_code"]=="SHA256_MISMATCH"

def test_without_an_indexed_extraction_nothing_is_reported(dsettings,vrepo,report,repo):
    job,sha=report
    with repo.connect() as c:c.execute("UPDATE km_csit_ingestion_jobs SET storage_references='{}'")
    res=Resolver(job,sha);p,_=processor(dsettings,vrepo,res);p.analysis_one()
    assert queued(vrepo)==[] and analysis_row(vrepo)["last_error_code"]=="NO_EXTRACTION"

def test_the_feature_stays_off_until_the_resolver_exists(dsettings):
    assert dsettings.analysis_results_enabled is False
    assert "v2-analysis" not in [l for _,l in V2Processor(dsettings,None,None,None).steps()]
    assert "v2-analysis" in [l for _,l in V2Processor(replace(dsettings,analysis_results_enabled=True),None,None,None).steps()]

# ---------- LLM extraction through the gateway (worker image has no src.web_api) ----------
def test_semantic_extraction_calls_the_configured_gateway(tmp_path,monkeypatch):
    from src.csit_integration_v1 import doclib_llm
    key=tmp_path/"k";key.write_text("secret-key\n")
    monkeypatch.setenv("KM_CSIT_LLM_BASE_URL","http://gw.invalid/v1/");monkeypatch.setenv("KM_CSIT_LLM_MODEL","m1");monkeypatch.setenv("KM_CSIT_LLM_API_KEY_FILE",str(key))
    seen={}
    def handler(r):
        seen["url"]=str(r.url);seen["auth"]=r.headers["authorization"];seen["body"]=json.loads(r.content)
        return httpx.Response(200,json={"choices":[{"message":{"content":"{\"documentType\":\"Manual\"}"}}]})
    real=httpx.post
    monkeypatch.setattr(httpx,"post",lambda url,**k:httpx.Client(transport=httpx.MockTransport(handler)).post(url,**k))
    assert doclib_llm.complete("hi")=="{\"documentType\":\"Manual\"}"
    assert seen["url"]=="http://gw.invalid/v1/chat/completions" and seen["auth"]=="Bearer secret-key" and seen["body"]["model"]=="m1" and seen["body"]["messages"][0]["content"]=="hi"
