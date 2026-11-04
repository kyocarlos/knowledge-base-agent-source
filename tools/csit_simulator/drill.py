"""End-to-end drill: simulator (as CSIT) <-> real KM routes + real worker over real HTTP.

    TEST_DATABASE_URL=postgresql://... python -m tools.csit_simulator.drill

KM here is the production code (api, repository, worker, pipeline, deletion) with an in-memory vector store and a
static bearer in place of Shared Identity. To drill against a deployed KM instead, run `serve` and drive /sim/* yourself.
"""
import os,sys,socket,tempfile,threading,time,uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import httpx,psycopg,uvicorn
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from fastapi import HTTPException
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.api import create_app as km_app
from src.csit_integration_v1.auth import ServiceIdentity
from src.csit_integration_v1.doclib_repository import DocLibRepository
from src.csit_integration_v1.repository import Repository
from src.csit_integration_v1.doclib_client import DocLibClient
from src.csit_integration_v1.doclib_pipeline import DocLibPipeline,DocLibQdrantWriter
from src.csit_integration_v1.doclib_deletion import DeletionExecutor
from src.csit_integration_v1.doclib_worker import DocLibWorker
from src.csit_integration_v1.doclib_metadata import make_semantic_extractor
from tools.csit_simulator.sim import Sim,create_app as sim_app

TOKEN="drill-token"

class FakeQdrant:
    def __init__(self):self.points={}
    @staticmethod
    def _m(p,f):return all(p["payload"].get(c.key)==c.match.value for c in f.must)
    def create_payload_index(self,*a,**k):pass
    def upsert(self,collection_name,points,wait=True):
        for p in points:self.points[(collection_name,str(p.id))]={"c":collection_name,"payload":p.payload}
    def delete(self,collection,points_selector,wait=True):
        for k in [k for k,p in self.points.items() if p["c"]==collection and self._m(p,points_selector)]:del self.points[k]
    def count(self,collection,count_filter,exact=True):
        return SimpleNamespace(count=sum(1 for p in self.points.values() if p["c"]==collection and self._m(p,count_filter)))
    def ids(self):return {p["payload"]["document_file_id"] for p in self.points.values()}

class StaticAuth:
    def headers(self):return {"Authorization":"Bearer "+TOKEN}
class StaticValidator:
    def validate(self,token):
        if token!=TOKEN:raise HTTPException(401,"bad token")
        return ServiceIdentity("csit-drill",frozenset({"km.ingestion.submit"}))

def free_port():
    with socket.socket() as s:s.bind(("127.0.0.1",0));return s.getsockname()[1]
def serve(app,port):
    srv=uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=port,log_level="error"))
    threading.Thread(target=srv.run,daemon=True).start()
    for _ in range(100):
        if srv.started:return srv
        time.sleep(.05)
    raise RuntimeError("server did not start")

def wait(cond,seconds=15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if cond():return True
        time.sleep(.1)
    return False

def main():
    raw=os.environ.get("TEST_DATABASE_URL") or sys.exit("set TEST_DATABASE_URL to a PostgreSQL server you may create a schema in")
    schema="csit_drill_"+uuid.uuid4().hex[:8]
    with psycopg.connect(raw,autocommit=True) as c:c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn=make_conninfo(raw,options="-c search_path="+schema)
    with psycopg.connect(dsn,autocommit=True) as c:
        for m in ("20261007_csit_integration_v1.sql","20261014_csit_integration_v1_nullable_lineage.sql","20261104_csit_document_library_v1.sql"):
            c.execute((ROOT/"migrations"/m).read_text(encoding="utf-8"))
        c.execute("CREATE TABLE km_users(user_id text PRIMARY KEY,status text,is_admin boolean)")
        c.execute("CREATE TABLE km_audit_events(event_id text PRIMARY KEY,occurred_at bigint,actor_user_id text,target_user_id text,event_type text,detail_json text)")
    sim_port,km_port=free_port(),free_port()
    sim=Sim(f"http://127.0.0.1:{km_port}",TOKEN);serve(sim_app(sim),sim_port)
    store=Path(tempfile.mkdtemp(prefix="csit-drill-"))
    # The 0o077 secret-file check cannot hold on Windows and no real secret is used here.
    Settings.validate=lambda self:None
    settings=Settings(enabled=True,doclib_enabled=True,db_url=dsn,csit_base_url=f"http://127.0.0.1:{sim_port}",storage_root=str(store),
        retry_delays=(0,0),callback_retry_delays=(0,0,0,0),poll_seconds=.1,timeout=5,chunk_size=400)
    drepo=DocLibRepository(dsn)
    serve(km_app(settings,Repository(dsn),StaticValidator(),doclib=drepo),km_port)
    q=FakeQdrant()
    client=DocLibClient(settings,StaticAuth())
    writer=DocLibQdrantWriter(q,"docs",lambda chunks:[[.1,.2] for _ in chunks],settings.chunk_size)
    semantic=make_semantic_extractor(lambda p:'{"documentType":"Manual","summary":"Wi-Fi 7 access point setup","keywords":["Wi-Fi 7","access point","nonexistent term"]}')
    worker=DocLibWorker(settings,drepo,client,DocLibPipeline(settings,drepo,client,writer,semantic=semantic),
        DeletionExecutor(drepo,settings.storage_root,qdrant=q,doclib_collection="docs",report_collections=("reports",)))
    stop=threading.Event();threading.Thread(target=worker.run,args=(stop,),daemon=True).start()

    S=f"http://127.0.0.1:{sim_port}"
    post=lambda path,body=None:httpx.post(S+path,json=body or {},timeout=30).json()
    state=lambda:httpx.get(S+"/sim/state").json()
    job=lambda cid:next(j for j in state()["jobs"] if j["csitJobId"]==cid)
    dele=lambda rid:next(d for d in state()["deletions"] if d["deletionRequestId"]==rid)
    text="CSIT 測試文件。This document describes the Wi-Fi 7 access point setup procedure. "*8
    results=[]
    def check(name,ok,note=""):
        results.append((name,bool(ok),note));print(("PASS  " if ok else "FAIL  ")+name+(("  -- "+str(note)) if note and not ok else ""),flush=True)
    def done(cid,final=("Completed","Failed")):return wait(lambda:job(cid)["state"] in final and job(cid)["state"]!="Accepted")

    # 1 happy path
    a=post("/sim/jobs",{"fileName":"manual.txt","contentText":text});ca=a["csitJobId"]
    check("1 happy path: 202 then Completed",done(ca) and job(ca)["state"]=="Completed",job(ca)["state"])
    j=job(ca);check("1 callbacks are Processing -> Completed",j["callbackStatuses"]==["Processing","Completed"],j["callbackStatuses"])
    check("1 every verdict passes",all(v["ok"] for v in j["verdicts"]),[v for v in j["verdicts"] if not v["ok"]])
    r=j["result"] or {}
    check("1 metadata: LLM fields kept, invented keyword dropped",r.get("document",{}).get("documentType")=="Manual" and r["document"]["keywords"]==["Wi-Fi 7","access point"],r.get("document"))
    check("1 vectors stamped with the file id",a["documentFileId"] in q.ids())

    # 2 resend is idempotent
    again=post(f"/sim/jobs/{ca}/resend")
    check("2 resend returns the same kmJobId",again["kmJobId"]==j["kmJobId"] and all(v["ok"] for v in again["verdicts"]))

    # 3 sha mismatch
    b=post("/sim/jobs",{"fileName":"bad.txt","contentText":text,"downloadFault":"tamper"});cb=b["csitJobId"]
    check("3 tampered download -> Failed, not retried",done(cb) and job(cb)["state"]=="Failed",job(cb)["state"])
    check("3 no vectors for the failed file",b["documentFileId"] not in q.ids())
    check("3 only one download attempt",len(job(cb)["downloads"])==1,len(job(cb)["downloads"]))

    # 4 transient download failure retries silently
    c=post("/sim/jobs",{"fileName":"flaky.txt","contentText":text,"downloadFault":"unavailable","downloadFailures":2});cc=c["csitJobId"]
    check("4 two 503s then Completed",done(cc) and job(cc)["state"]=="Completed",job(cc)["state"])
    check("4 no status regress (Processing -> Completed only)",job(cc)["callbackStatuses"]==["Processing","Completed"],job(cc)["callbackStatuses"])
    check("4 three download attempts",len(job(cc)["downloads"])==3,len(job(cc)["downloads"]))

    # 5 bad token
    d=post("/sim/jobs",{"fileName":"x.txt","contentText":text,"badToken":True})
    check("5 wrong bearer is rejected 401",all(v["ok"] for v in d["verdicts"]) and d["state"]=="New",d["verdicts"])

    # 6 CSIT outage while KM reports: KM must retry and still deliver in order
    post("/sim/faults",{"callbackFailures":3,"callbackStatus":503})
    e=post("/sim/jobs",{"fileName":"outage.txt","contentText":text});ce=e["csitJobId"]
    check("6 callbacks survive a CSIT 503 outage",done(ce) and job(ce)["state"]=="Completed",job(ce)["state"])
    check("6 order kept after retries",job(ce)["callbackStatuses"]==["Processing","Completed"],job(ce)["callbackStatuses"])

    # 7 unsupported format
    f=post("/sim/jobs",{"fileName":"tool.exe","contentText":"MZ binary"});cf=f["csitJobId"]
    check("7 unsupported format -> Failed without download",done(cf) and job(cf)["state"]=="Failed" and not job(cf)["downloads"])

    # 8 deletion of one of two same-name files
    g1=post("/sim/jobs",{"fileName":"same.txt","contentText":text+"one"});g2=post("/sim/jobs",{"fileName":"same.txt","contentText":text+"two"})
    done(g1["csitJobId"]);done(g2["csitJobId"])
    dl=post("/sim/deletions",{"documentFileId":g1["documentFileId"]});rid=dl["deletionRequestId"]
    check("8 deletion accepted with 202",dl["state"]=="Accepted" and all(v["ok"] for v in dl["verdicts"]))
    check("8 deletion reaches Completed",wait(lambda:dele(rid)["state"]=="Completed"),dele(rid)["state"])
    dd=dele(rid)
    check("8 deletion verdicts pass",all(v["ok"] for v in dd["verdicts"]),[v for v in dd["verdicts"] if not v["ok"]])
    check("8 callbacks Processing -> Completed",dd["callbackStatuses"]==["Processing","Completed"],dd["callbackStatuses"])
    check("8 only the targeted file is gone",g1["documentFileId"] not in q.ids() and g2["documentFileId"] in q.ids())
    check("8 cleanup reports chunks Deleted, graph NotPresent",(dd["result"] or {}).get("cleanup",{}).get("chunks")=="Deleted" and dd["result"]["cleanup"]["graphRelations"]=="NotPresent",dd["result"])

    # 9 deletion is idempotent, and a deleted file cannot be ingested again
    again=post(f"/sim/deletions",{"deletionRequestId":rid,"documentFileId":g1["documentFileId"]})
    check("9 same deletionRequestId returns the same kmDeletionJobId",again["kmDeletionJobId"]==dd["kmDeletionJobId"])
    late=post(f"/sim/jobs/{g1['csitJobId']}/resend")
    check("9 late ingestion of a deleted file is refused (409)",late["state"]=="Rejected" and "409" in str(late["timeline"][-1]),late["timeline"][-1:])
    check("9 nothing was re-indexed",g1["documentFileId"] not in q.ids())

    rep=httpx.get(S+"/sim/report").json()
    # scenario 3/5/7 deliberately provoke refusals; those verdicts are expectations, not violations.
    check("overall: simulator recorded no spec violations by KM",not rep["violations"],rep["violations"])
    stop.set()
    with psycopg.connect(raw,autocommit=True) as cn:cn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
    bad=[r for r in results if not r[1]]
    print(f"\n{len(results)-len(bad)}/{len(results)} checks passed")
    sys.exit(1 if bad else 0)

if __name__=="__main__":main()
