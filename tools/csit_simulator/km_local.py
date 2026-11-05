"""A real KM (routes, repository, worker, pipeline, deletion) on a local PostgreSQL, for demos and the drill.

Stand-ins: vector store in memory, a static bearer instead of Shared Identity, and (unless an LLM is configured) a rule-based
stub for documentType / summary / keywords. Everything the spec exercises (202, download, SHA256, callbacks, tombstone, cleanup) is KM's own code.
"""
import json,re,socket,tempfile,threading,time,uuid
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
import psycopg,uvicorn
from fastapi import HTTPException
from psycopg import sql
from psycopg.conninfo import make_conninfo
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.api import create_app as km_app
from src.csit_integration_v1.auth import ServiceIdentity
from src.csit_integration_v1.repository import Repository
from src.csit_integration_v1.v2_repository import V2Repository
from src.csit_integration_v1.v2_pipeline import V2Pipeline,V2QdrantWriter
from src.csit_integration_v1.v2_worker import V2Processor
from src.csit_integration_v1.client import CsitIntegrationClient
from src.csit_integration_v1.pipeline import Pipeline
from src.csit_integration_v1.worker import Worker
from src.csit_integration_v1.writers import StorageWriter,QdrantWriter
from src.csit_integration_v1.doclib_client import DocLibClient
from src.csit_integration_v1.doclib_pipeline import DocLibPipeline,DocLibQdrantWriter
from src.csit_integration_v1.doclib_deletion import DeletionExecutor
from src.csit_integration_v1.doclib_worker import DocLibWorker
from src.csit_integration_v1.doclib_metadata import make_semantic_extractor

ROOT=Path(__file__).resolve().parents[2]
MIGRATIONS=("20261007_csit_integration_v1.sql","20261014_csit_integration_v1_nullable_lineage.sql","20261104_csit_document_library_v1.sql","20261105_csit_integration_v2.sql")

class MemoryQdrant:
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
    def set_payload(self,collection,payload,points,wait=True):
        for p in self.points.values():
            if p["c"]==collection and self._m(p,points):p["payload"].update(payload)
    def ids(self):return {p["payload"].get("document_file_id") or p["payload"].get("document_id") for p in self.points.values()}
    def states(self):
        out={}
        for p in self.points.values():out[p["payload"].get("document_file_id") or p["payload"].get("document_id")]=p["payload"].get("index_state","Active")
        return out

def stub_semantic(text):
    """Rule-based stand-in for the LLM so a demo needs no model: shows the shape, not real understanding."""
    low=text.lower()
    kind="Other"
    for words,k in ((("test report","測試報告"),"TestReport"),(("manual","手冊","user guide"),"Manual"),(("specification","規格"),"Specification"),
                    (("sop","作業程序","procedure"),"SOP"),(("meeting","會議"),"MeetingMinutes"),(("issue","root cause","問題分析"),"IssueAnalysis")):
        if any(w in low for w in words):kind=k;break
    words=Counter(w for w in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}",text) if w.lower() not in {"this","that","with","from","which","there","their"})
    return {"documentType":kind,"summary":" ".join(text.split())[:160],"keywords":[w for w,_ in words.most_common(8)]}

class StaticAuth:
    def __init__(self,token):self.token=token
    def headers(self):return {"Authorization":"Bearer "+self.token}
class StaticValidator:
    def __init__(self,token):self.token=token
    def validate(self,token):
        if token!=self.token:raise HTTPException(401,"bad token")
        return ServiceIdentity("csit-sim",frozenset({"km.ingestion.submit"}))

def free_port():
    with socket.socket() as s:s.bind(("127.0.0.1",0));return s.getsockname()[1]
def serve(app,port,host="127.0.0.1"):
    srv=uvicorn.Server(uvicorn.Config(app,host=host,port=port,log_level="error"))
    threading.Thread(target=srv.run,daemon=True).start()
    for _ in range(200):
        if srv.started:return srv
        time.sleep(.05)
    raise RuntimeError("server did not start on port %s"%port)

class LocalKm:
    def __init__(self,pg_url,csit_base_url,token,km_port,*,semantic="stub",retry_delays=(2,5,10),schema=None,poll=.3,callback_delays=(1,2,5,10)):
        self.raw=pg_url;self.schema=schema or "csit_km_"+uuid.uuid4().hex[:8]
        with psycopg.connect(pg_url,autocommit=True) as c:c.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(self.schema)))
        self.dsn=make_conninfo(pg_url,options="-c search_path="+self.schema)
        with psycopg.connect(self.dsn,autocommit=True) as c:
            c.execute("CREATE TABLE IF NOT EXISTS km_users(user_id text PRIMARY KEY,status text,is_admin boolean)")
            c.execute("CREATE TABLE IF NOT EXISTS km_audit_events(event_id text PRIMARY KEY,occurred_at bigint,actor_user_id text,target_user_id text,event_type text,detail_json text)")
            if not c.execute("SELECT to_regclass('km_csit_doclib_jobs')").fetchone()[0]:
                for m in MIGRATIONS:c.execute((ROOT/"migrations"/m).read_text(encoding="utf-8"))
        Settings.validate=lambda self:None # the 0o077 secret-file check has no Windows meaning and no real secret is used
        self.store=Path(tempfile.mkdtemp(prefix="csit-km-"))
        self.settings=Settings(enabled=True,doclib_enabled=True,db_url=self.dsn,csit_base_url=csit_base_url,storage_root=str(self.store),
            retry_delays=tuple(retry_delays),callback_retry_delays=tuple(callback_delays),poll_seconds=poll,timeout=10,chunk_size=400,
            analysis_results_enabled=True) # the local KM stands in for a KM whose CSIT has deployed the Correlation Resolver
        self.repo=V2Repository(self.dsn);self.q=MemoryQdrant();self.port=km_port
        self.server=serve(km_app(self.settings,Repository(self.dsn),StaticValidator(token),doclib=self.repo),km_port)
        client=DocLibClient(self.settings,StaticAuth(token))
        writer=DocLibQdrantWriter(self.q,"docs",lambda chunks:[[.1,.2] for _ in chunks],self.settings.chunk_size)
        if semantic=="stub":
            extractor=make_semantic_extractor(lambda p:json.dumps(stub_semantic(p.split("文件內容：\n",1)[-1]),ensure_ascii=False))
        else:extractor=semantic if callable(semantic) else None
        v2writer=V2QdrantWriter(self.q,"docs",lambda chunks:[[.1,.2] for _ in chunks],self.settings.chunk_size,extra_collections=("reports",))
        self.v2=V2Processor(self.settings,self.repo,V2Pipeline(self.settings,self.repo,client,v2writer,semantic=extractor),v2writer,report_collections=("reports",),client=client)
        self.worker=DocLibWorker(self.settings,self.repo,client,DocLibPipeline(self.settings,self.repo,client,writer,semantic=extractor),
            DeletionExecutor(self.repo,self.settings.storage_root,qdrant=self.q,doclib_collection="docs",report_collections=("reports",)),
            extra_steps=self.v2.steps())
        # Test Report v1 (route, worker, callbacks): generic parse -> storage + vectors; there is no Neo4j / TimescaleDB here.
        v1client=CsitIntegrationClient(self.settings,StaticAuth(token))
        v1writers={"storage":StorageWriter(self.settings.storage_root),"qdrant":QdrantWriter(self.q,"reports",lambda chunks:[[.1,.2] for _ in chunks],self.settings.chunk_size)}
        self.v1worker=Worker(self.settings,Repository(self.dsn),v1client,Pipeline(self.settings,Repository(self.dsn),v1client,v1writers,numeric_rules=()),tombstones=self.repo)
        self.stop=threading.Event()
        threading.Thread(target=self.worker.run,args=(self.stop,),daemon=True).start()
        threading.Thread(target=self.v1worker.run,args=(self.stop,),daemon=True).start()
    def inspect(self):
        with self.repo.connect() as c:
            jobs=[{"kmJobId":r["km_job_id"],"status":r["status"],"phase":r["phase"],"attempts":r["attempt_count"],"lastError":r["last_error_code"] or "",
                   "nextRetry":str(r["next_retry_at"] or "")[:19],"fileId":str(r["document_file_id"])[:8]} for r in c.execute("SELECT * FROM km_csit_doclib_jobs ORDER BY created_at DESC LIMIT 50")]
            dels=[{"kmDeletionJobId":r["km_deletion_job_id"],"status":r["status"],"phase":r["phase"],"attempts":r["attempt_count"],"lastError":r["last_error_code"] or "",
                   "sourceKey":r["source_key"][:8]} for r in c.execute("SELECT * FROM km_csit_deletion_jobs ORDER BY created_at DESC LIMIT 50")]
            tombs=[{"sourceType":r["source_type"],"sourceKey":r["source_key"]} for r in c.execute("SELECT * FROM km_csit_tombstones ORDER BY created_at DESC")]
            out=[{"kind":r["kind"],"status":r["status"],"payloadStatus":r["payload"]["status"],"attempts":r["attempt_count"],"lastError":r["last_error_code"] or ""}
                 for r in c.execute("SELECT * FROM km_csit_v13_callbacks ORDER BY sequence DESC LIMIT 50")]
        v2jobs=[]
        with self.repo.connect() as c:
            v2jobs=[{"kmJobId":r["km_job_id"],"sourceType":r["source_type"],"status":r["status"],"phase":r["phase"],"indexState":r["index_state"],
                     "lastError":r["last_error_code"] or "","docId":str(r["document_id"])[:8],"version":r["version"]} for r in c.execute("SELECT * FROM km_csit_v2_jobs ORDER BY created_at DESC LIMIT 50")]
            changes=[{"kmChangeJobId":r["km_change_job_id"],"status":r["status"],"revision":r["source_revision"],"lastError":r["last_error_code"] or ""}
                     for r in c.execute("SELECT * FROM km_csit_v2_changes ORDER BY created_at DESC LIMIT 50")]
        with self.repo.connect() as c:
            reports=[{"kmJobId":str(r["job_id"])[:8],"documentId":r["document_id"][:8],"version":r["version"],"status":r["status"],"phase":r["phase"],"lastError":r["last_error_code"] or ""}
                     for r in c.execute("SELECT * FROM km_csit_ingestion_jobs ORDER BY created_at DESC LIMIT 50")]
            analysis=[{"v1Job":str(r["v1_job_id"])[:8],"status":r["status"],"attempts":r["attempt_count"],"lastError":r["last_error_code"] or ""} for r in c.execute("SELECT * FROM km_csit_v2_analysis")]
        by={}
        for p in list(self.q.points.values()):
            fid=p["payload"].get("document_file_id") or p["payload"].get("document_id");e=by.setdefault(fid,{"documentFileId":fid,"chunks":0,"sample":p["payload"]["content"][:70]});e["chunks"]+=1
        files=[{"path":str(f.relative_to(self.store)),"bytes":f.stat().st_size} for f in sorted(self.store.rglob("*")) if f.is_file()]
        return {"jobs":jobs,"reportJobs":reports,"analysis":analysis,"v2Jobs":v2jobs,"metadataChanges":changes,"deletions":dels,"tombstones":tombs,"outbox":out,"vectors":list(by.values()),"files":files}
    def close(self):self.stop.set()
