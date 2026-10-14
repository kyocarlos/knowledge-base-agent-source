import os,json,threading,logging
from pathlib import Path
from contextlib import asynccontextmanager
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.worker import Worker
from src.csit_integration_v1.writers import StorageWriter,QdrantWriter,Neo4jWriter,TimescaleWriter
from src.km_control import ControlRegistry,verify_entry_session,ControlError
from .repository import DevRepository
from .pipeline import LocalUpload,DevPipeline,DEV_GRAPH_IDENTIFIERS,DEV_GRAPH_CONSTRAINTS
from .api import create_app

class ReadOnlyControlRegistry(ControlRegistry):
    def _initialize(self):
        with self._connection() as c:
            c.execute("SELECT user_id FROM km_users LIMIT 0")
            c.execute("SELECT user_id FROM km_instance_grants LIMIT 0")

class DevWorker(Worker):
    def callback_one(self):return False

def application():
    os.umask(0o077)
    zone=os.environ["KM_DEV_UPLOAD_ZONE"]
    if zone not in os.environ["KM_DEV_UPLOAD_ALLOWED_ZONES"].split(","):raise ValueError("unapproved DEV zone")
    enabled=os.environ.get("KM_DEV_UPLOAD_ENABLED","false")=="true"
    root=Path(os.environ["KM_DEV_UPLOAD_STORAGE_ROOT"])
    schema=os.environ["KM_DEV_UPLOAD_JOB_SCHEMA"]
    s=Settings(db_url=os.environ["KM_CONTROL_DB_URL"],storage_root=str(root/"jobs"),
        max_file_size=int(os.environ.get("KM_DEV_UPLOAD_MAX_FILE_SIZE","20971520")),
        poll_seconds=1,lease_seconds=120,retry_delays=(10,30,90))
    repo=DevRepository(s.db_url,schema);repo.check_schema()
    local=LocalUpload(root/"uploads")
    control=ReadOnlyControlRegistry.from_environment()
    allowed=set(os.environ["KM_DEV_UPLOAD_ALLOWED_USERS"].split(","))
    from .auth import EntryAuthenticator
    authenticate=EntryAuthenticator(zone,control,allowed)
    from qdrant_client import QdrantClient
    from neo4j import GraphDatabase
    qdrant=QdrantClient(url=os.environ["QDRANT_URL"],timeout=30)
    collection=os.environ["KM_DEV_UPLOAD_COLLECTION"]
    neo=GraphDatabase.driver(os.environ["NEO4J_URI"],auth=(os.environ["NEO4J_USER"],os.environ["NEO4J_PASSWORD"]))
    graph_db=os.environ["KM_DEV_UPLOAD_GRAPH_DATABASE"]
    numeric_schema=os.environ["KM_DEV_UPLOAD_NUMERIC_SCHEMA"]
    def numeric_connection():
        return psycopg.connect(os.environ["TIMESCALEDB_URL"],row_factory=dict_row,options="-csearch_path="+numeric_schema)
    model=None;model_lock=threading.Lock()
    def embed(texts):
        nonlocal model
        with model_lock:
            if model is None:
                from sentence_transformers import SentenceTransformer
                model=SentenceTransformer(os.environ["KM_DEV_UPLOAD_EMBEDDING_MODEL"],device="cpu")
            return model.encode(texts,normalize_embeddings=True).tolist()
    writers={"storage":StorageWriter(root/"jobs"),"qdrant":QdrantWriter(qdrant,collection,embed,s.chunk_size),
        "neo4j":Neo4jWriter(neo,graph_db,DEV_GRAPH_IDENTIFIERS,DEV_GRAPH_CONSTRAINTS),"timescale":TimescaleWriter(numeric_connection)}
    rules=json.loads(Path(os.environ["KM_DEV_UPLOAD_NUMERIC_RULES"]).read_text())
    pipeline=DevPipeline(s,repo,local,writers,rules)
    worker=DevWorker(s,repo,local,pipeline)
    def evidence(job):
        refs=job["storage_references"];p=job["request_payload"]
        q=refs.get("Qdrant",{});points=qdrant.retrieve(collection_name=collection,ids=q.get("pointIds",[]),with_vectors=False) if q.get("pointIds") else []
        vector_ok=bool(points) and len(points)==len(q["pointIds"]) and all(x.payload.get("lineage",{}).get("dataZone")==zone and x.payload.get("source_system")=="KM_DEV_UPLOAD" for x in points)
        g=refs.get("Neo4j",{})
        with neo.session(database=graph_db) as session:
            nodes=list(session.run("MATCH (e:KmDevKnowledgeEntity) WHERE e.id IN $ids RETURN e.lineage AS lineage",ids=g.get("entityIds",[])))
        graph_ok=bool(nodes) and len(nodes)==len(g.get("entityIds",[])) and all(json.loads(x["lineage"]).get("dataZone")==zone for x in nodes)
        t=refs.get("TimescaleDB",{})
        with numeric_connection() as c:
            rows=c.execute("SELECT source_system,lineage FROM km_csit_numeric_points WHERE point_id=ANY(%s::uuid[])",(t.get("pointIds",[]),)).fetchall()
        numeric_ok=bool(rows) and len(rows)==len(t.get("pointIds",[])) and all(x["source_system"]=="KM_DEV_UPLOAD" and x["lineage"].get("dataZone")==zone for x in rows)
        normalized=root/"jobs"/str(job["job_id"])/"normalized.json"
        storage_ok=normalized.is_file() and json.loads(normalized.read_text())["lineage"]["dataZone"]==zone
        with repo.connect() as c:callbacks=c.execute("SELECT count(*) AS n FROM km_csit_callback_deliveries WHERE job_id=%s",(job["job_id"],)).fetchone()["n"]
        return {"jobId":str(job["job_id"]),"dataZone":zone,"testRunId":p["testRunId"],"status":job["status"],
            "writers":{"Storage":{"verified":storage_ok},"Qdrant":{"verified":vector_ok,"count":len(points)},
                "Neo4j":{"verified":graph_ok,"count":len(nodes)},
                "TimescaleDB":{"verified":numeric_ok if t else None,"count":len(rows),"applicable":bool(t)}},
            "callbackCount":callbacks,"csitCalled":False}
    def search(term,owner):
        from qdrant_client.models import Filter,FieldCondition,MatchValue
        owned_ids={r["document_id"] for r in repo.list_owned(owner,limit=1000)}
        filt=Filter(must=[FieldCondition(key="source_system",match=MatchValue(value="KM_DEV_UPLOAD")),
             FieldCondition(key="lineage.dataZone",match=MatchValue(value=zone))])
        hits=[];offset=None;scanned=0
        while scanned<10000:
            points,offset=qdrant.scroll(collection_name=collection,scroll_filter=filt,limit=200,offset=offset,with_vectors=False)
            scanned+=len(points)
            for point in points:
                data=point.payload
                if data.get("document_id") in owned_ids and term.casefold() in data.get("content","").casefold():
                    hits.append({"documentId":data["document_id"],"fileName":data["doc_name"],"content":data["content"][:1500],"dataZone":zone})
                    if len(hits)>=20:break
            if offset is None or len(hits)>=20:break
        return {"dataZone":zone,"term":term,"count":len(hits),"hits":hits,"truncated":offset is not None}
    app=create_app(s,repo,local,authenticate,set(os.environ["KM_DEV_UPLOAD_ALLOWED_ORIGINS"].split(",")),zone,
        enabled=enabled,evidence=evidence,search=search)
    stop=threading.Event()
    @asynccontextmanager
    async def lifespan(app):
        thread=threading.Thread(target=worker.run,args=(stop,),daemon=True)
        if enabled:thread.start()
        yield
        stop.set()
        if enabled:thread.join(timeout=15)
        neo.close();qdrant.close()
    app.router.lifespan_context=lifespan
    return app
