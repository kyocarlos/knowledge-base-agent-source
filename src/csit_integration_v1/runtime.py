"""Deployment entrypoints. No fake auth handler or automatic runtime DDL."""
import json,threading,signal,os,logging
from pathlib import Path
import psycopg
from .config import Settings
from .repository import Repository
from .api import create_app

def application():
    s=Settings.from_env();s.validate()
    doclib=None
    if s.doclib_enabled or os.getenv("KM_CSIT_DOCLIB_ROUTES")=="1":
        from .v2_repository import V2Repository
        doclib=V2Repository(s.db_url)
    return create_app(s,Repository(s.db_url),doclib=doclib)

def _cache_clear(resource):
    """Search/answer caches are keyed by query text, so a deleted source invalidates the search cache wholesale (the file-based QA cache is not Redis and is not covered)."""
    from src.web_api.cache import cache_clear_pattern
    return sum(cache_clear_pattern(p) for p in ("search:*",))

def worker():
    from .auth import ClientCredentialsProvider
    from .client import CsitIntegrationClient
    from .pipeline import Pipeline
    from .worker import Worker
    from .writers import StorageWriter,QdrantWriter,Neo4jWriter,TimescaleWriter
    s=Settings.from_env();s.validate()
    if not s.enabled:raise SystemExit("Integration disabled; M2M Client Credentials pending")
    repo=Repository(s.db_url);repo.check_schema()
    auth=ClientCredentialsProvider(s);client=CsitIntegrationClient(s,auth)
    writers={"storage":StorageWriter(s.storage_root)}
    # Mandatory downstream settings belong to the approved target KM data-zone deployment.
    from src.vector_store import VectorStore
    vector=VectorStore()
    if not vector.available or vector.client is None:raise SystemExit("Qdrant unavailable")
    writers["qdrant"]=QdrantWriter(vector.client,os.environ["KM_CSIT_QDRANT_COLLECTION"],vector.encode,s.chunk_size)
    if os.getenv("KM_CSIT_NEO4J_URI"):
        from neo4j import GraphDatabase
        secret=Path(os.environ["KM_CSIT_NEO4J_SECRET_FILE"]).read_text().strip()
        driver=GraphDatabase.driver(os.environ["KM_CSIT_NEO4J_URI"],auth=(os.environ["KM_CSIT_NEO4J_USER"],secret))
        writers["neo4j"]=Neo4jWriter(driver,os.environ["KM_CSIT_NEO4J_DATABASE"])
    if os.getenv("KM_CSIT_TIMESCALE_DSN_FILE"):
        dsn=Path(os.environ["KM_CSIT_TIMESCALE_DSN_FILE"]).read_text().strip()
        writers["timescale"]=TimescaleWriter(lambda:psycopg.connect(dsn))
    rules=json.loads(Path(os.environ["KM_CSIT_NUMERIC_RULES_FILE"]).read_text())
    reports=None
    if os.getenv("KM_CSIT_REPORT_TEMPLATES")=="1":
        # Registered report templates (src/report_numeric): needs the TimescaleDB, Neo4j and Qdrant targets together.
        if "timescale" not in writers or "neo4j" not in writers:raise SystemExit("Report templates need KM_CSIT_TIMESCALE_DSN_FILE and KM_CSIT_NEO4J_URI")
        from .report_adapter import ReportAdapter
        reports=ReportAdapter(lambda:psycopg.connect(dsn,autocommit=True),driver,vector.client)
    pipeline=Pipeline(s,repo,client,writers,numeric_rules=rules,reports=reports)
    doclib_worker=None
    if s.doclib_enabled:
        # Spec v1.3 document-library ingestion + verified deletion. Same M2M identity, own tables, own switch.
        from .v2_repository import V2Repository
        from .doclib_client import DocLibClient
        from .doclib_pipeline import DocLibPipeline,DocLibQdrantWriter
        from .doclib_deletion import DeletionExecutor
        from .doclib_worker import DocLibWorker
        from .v2_pipeline import V2Pipeline,V2QdrantWriter
        from .v2_worker import V2Processor
        from .doclib_metadata import make_semantic_extractor
        drepo=V2Repository(s.db_url);drepo.check_schema()
        collection=os.getenv("KM_CSIT_DOCLIB_QDRANT_COLLECTION") or os.environ["KM_CSIT_QDRANT_COLLECTION"]
        qwriter=DocLibQdrantWriter(vector.client,collection,vector.encode,s.chunk_size);qwriter.ensure_index()
        v2writer=V2QdrantWriter(vector.client,collection,vector.encode,s.chunk_size);v2writer.ensure_index()
        semantic=None
        if os.getenv("KM_CSIT_DOCLIB_LLM")=="1":
            from .doclib_llm import complete
            semantic=make_semantic_extractor(complete)
        dclient=DocLibClient(s,auth)
        report_collections=tuple(x for x in (os.getenv("KM_CSIT_QDRANT_COLLECTION"),"ai_km_knowledge_v1") if x)
        executor=DeletionExecutor(drepo,s.storage_root,qdrant=vector.client,doclib_collection=collection,report_collections=report_collections,
            neo4j_driver=driver if os.getenv("KM_CSIT_NEO4J_URI") else None,neo4j_database=os.getenv("KM_CSIT_NEO4J_DATABASE"),
            timescale_connect=(lambda:psycopg.connect(dsn)) if os.getenv("KM_CSIT_TIMESCALE_DSN_FILE") else None,cache_clear=_cache_clear)
        v2=V2Processor(s,drepo,V2Pipeline(s,drepo,dclient,v2writer,semantic=semantic),v2writer,report_collections=report_collections)
        doclib_worker=DocLibWorker(s,drepo,dclient,DocLibPipeline(s,drepo,dclient,qwriter,semantic=semantic),executor,extra_steps=v2.steps())
        worker_obj_tombstones=drepo
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    logging.basicConfig(level=logging.INFO)
    threads=[]
    if doclib_worker is not None:
        t=threading.Thread(target=doclib_worker.run,args=(stop,),daemon=True);t.start();threads.append(t)
    try:Worker(s,repo,client,pipeline,tombstones=worker_obj_tombstones if doclib_worker is not None else None).run(stop)
    finally:
        stop.set()
        for t in threads:t.join(10)
        client.close();auth.close()
if __name__=="__main__":worker()
