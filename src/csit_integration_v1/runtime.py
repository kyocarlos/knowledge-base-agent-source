"""Deployment entrypoints. No fake auth handler or automatic runtime DDL."""
import json,threading,signal,os,logging
from pathlib import Path
import psycopg
from .config import Settings
from .repository import Repository
from .api import create_app

def application():
    s=Settings.from_env();s.validate()
    return create_app(s,Repository(s.db_url))

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
    stop=threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stop.set())
    logging.basicConfig(level=logging.INFO)
    try:Worker(s,repo,client,pipeline).run(stop)
    finally:client.close();auth.close()
if __name__=="__main__":worker()
