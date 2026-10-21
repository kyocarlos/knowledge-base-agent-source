import os,json,uuid,hashlib,io
from pathlib import Path
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
import pytest,psycopg
from psycopg import sql
from fastapi.testclient import TestClient
from fastapi import HTTPException
from dataclasses import replace
from src.km_control import issue_entry_session,ControlAuthorizationError
from src.km_dev_upload.auth import EntryAuthenticator
from src.km_dev_upload.repository import DevRepository
from src.km_dev_upload.api import create_app
from src.km_dev_upload.pipeline import LocalUpload,DevPipeline,DEV_GRAPH_IDENTIFIERS,DEV_GRAPH_CONSTRAINTS
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.worker import Worker
from src.csit_integration_v1.writers import StorageWriter,QdrantWriter,Neo4jWriter,TimescaleWriter
from src.csit_integration_v1.errors import LeaseLost
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams,Distance
ORIGIN="https://fake-km-dev.invalid"

class FixtureControl:
    def validate_entry_claims(self,sub,zone,role,epoch):
        if sub not in ("u1","u2") or zone not in ("da40","test") or role!="user" or epoch!=1:
            raise ControlAuthorizationError("test grant rejected")
    def get_user(self,sub):return SimpleNamespace(user_id=sub,username="tester" if sub=="u1" else "other")

@pytest.fixture
def zones(tmp_path,monkeypatch):
    import secrets
    monkeypatch.setenv("KM_ENTRY_SESSION_SIGNING_KEY",secrets.token_urlsafe(40))
    raw=os.environ["TEST_DATABASE_URL"];result={};schemas=[]
    template=Path("/migration/20261007_csit_integration_v1.sql").read_text().replace("source_system='CSIT'","source_system='KM_DEV_UPLOAD'").replace("event_type='TestReportCommitted'","event_type='KMDevTestUpload'")
    try:
        for zone in ("da40","test"):
            schema="dev_upload_test_"+uuid.uuid4().hex;schemas.append(schema)
            with psycopg.connect(raw) as c:c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            repo=DevRepository(raw,schema)
            with repo.connect() as c:c.execute(template)
            settings=Settings(db_url=raw,storage_root=str(tmp_path/zone/"jobs"),lease_seconds=1,retry_delays=(0,0),max_file_size=100000)
            local=LocalUpload(tmp_path/zone/"uploads")
            auth=EntryAuthenticator(zone,FixtureControl(),["tester","other"])
            app=create_app(settings,repo,local,auth,{ORIGIN},zone)
            client=TestClient(app);client.cookies.set("km_entry_session",issue_entry_session("u1",zone,"user",1))
            result[zone]=SimpleNamespace(repo=repo,settings=settings,local=local,app=app,client=client)
        yield result
    finally:
        for schema in schemas:
            with psycopg.connect(raw) as c:c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

def upload(z,content=b"report marker",**changes):
    query={"testRunId":"isolation1","documentId":"same-report","version":"1","fileName":"same.txt"}
    query.update(changes)
    return z.client.post("/api/dev-upload/jobs",params=query,headers={"Origin":ORIGIN,"X-KM-DEV-Upload":"1","Content-Type":"text/plain"},content=content)

def test_zone_session_and_owner_boundary(zones):
    a,b=zones["da40"],zones["test"]
    ja=upload(a,b"DA40_ONLY").json();jb=upload(b,b"TEST_ONLY").json()
    assert ja["jobId"]!=jb["jobId"] and ja["sha256"]!=jb["sha256"]
    assert a.client.get("/api/dev-upload/jobs/"+jb["jobId"]).status_code==404
    assert b.client.get("/api/dev-upload/jobs/"+ja["jobId"]+"/file").status_code==404
    b.client.cookies.set("km_entry_session",issue_entry_session("u1","da40","user",1))
    assert b.client.get("/api/dev-upload/jobs").status_code==401
    a.client.cookies.set("km_entry_session",issue_entry_session("u2","da40","user",1))
    assert a.client.get("/api/dev-upload/jobs/"+ja["jobId"]).status_code==404
    assert a.client.get("/api/dev-upload/jobs/"+ja["jobId"]+"/evidence").status_code==404

@pytest.mark.parametrize("cookie",["","garbage","signed-human-not-entry"])
def test_anonymous_and_malformed_cookie(zones,cookie):
    z=zones["da40"];z.client.cookies.set("km_entry_session",cookie)
    assert z.client.get("/api/dev-upload/jobs").status_code==401

def test_revoked_epoch_and_allowlist(zones):
    z=zones["da40"];z.client.cookies.set("km_entry_session",issue_entry_session("u1","da40","user",2))
    assert z.client.get("/api/dev-upload/me").status_code==401
    auth=EntryAuthenticator("da40",FixtureControl(),[])
    with pytest.raises(HTTPException) as e:auth(issue_entry_session("u1","da40","user",1))
    assert e.value.status_code==403

@pytest.mark.parametrize("origin,header",[(None,None),("https://evil.invalid","1"),(ORIGIN,None)])
def test_csrf(zones,origin,header):
    headers={"Content-Type":"text/plain"}
    if origin:headers["Origin"]=origin
    if header:headers["X-KM-DEV-Upload"]=header
    assert zones["da40"].client.post("/api/dev-upload/jobs",headers=headers,content=b"file").status_code==403

@pytest.mark.parametrize("changes",[{"dataZone":"test"},{"documentId":"../escape"},{"testRunId":""},{"version":"0"},{"fileName":"../escape.txt"},{"fileName":"long"*80+".txt"},{"fileName":"report.exe"}])
def test_metadata_rejection(zones,changes):
    assert upload(zones["da40"],**changes).status_code==422

def test_executable_size_empty_and_mime(zones):
    z=zones["da40"]
    assert upload(z,b"MZ executable").status_code==422
    assert upload(z,b"").status_code==422
    assert upload(z,b"x"*100001).status_code==413
    assert upload(z,b"text",fileName="report.csv").status_code==422
    assert list(z.local.root.glob("*"))==[]

def test_duplicate_and_conflicting_version(zones):
    z=zones["da40"];first=upload(z).json();second=upload(z).json()
    assert second["duplicate"] and first["jobId"]==second["jobId"]
    assert upload(z,b"changed").status_code==409
    assert upload(z,b"changed",version="2").status_code==202
    assert len(list(z.local.root.glob("*")))==2
    assert z.client.get("/api/dev-upload/jobs/"+first["jobId"]+"/file").content==b"report marker"

def test_concurrent_idempotency(zones):
    z=zones["da40"]
    with ThreadPoolExecutor(max_workers=8) as pool:responses=list(pool.map(lambda _:upload(z),range(16)))
    assert all(r.status_code==202 for r in responses)
    assert len({r.json()["jobId"] for r in responses})==1
    assert len(list(z.local.root.glob("*")))==1

def test_missing_schema_never_falls_back_to_csit(zones):
    repo=DevRepository(os.environ["TEST_DATABASE_URL"],"missing_"+uuid.uuid4().hex)
    with pytest.raises(psycopg.Error):repo.check_schema()

def test_disabled_endpoint(zones):
    z=zones["da40"];client=TestClient(create_app(z.settings,z.repo,z.local,lambda cookie:{"user_id":"u1"}, {ORIGIN},"da40",enabled=False))
    assert client.get("/api/dev-upload/jobs").status_code==404

def test_live_shared_pipeline_all_writers_two_zones(zones):
    from neo4j import GraphDatabase
    driver=GraphDatabase.driver(os.environ["TEST_NEO4J_URI"],auth=None)
    with driver.session(database="neo4j") as session:
        for statement in Path("/migration/20261007_km_dev_upload_graph.cypher").read_text().split(";"):
            if statement.strip():session.run(statement).consume()
    numeric_schemas=[];jobs={}
    try:
        for zone,z in zones.items():
            response=z.client.get("/api/dev-upload/sample?testRunId=isolation1")
            assert response.status_code==200
            uploaded=z.client.post("/api/dev-upload/jobs",params={"testRunId":"isolation1","documentId":"same-report","version":1,"fileName":"same.xlsx"},
                headers={"Origin":ORIGIN,"X-KM-DEV-Upload":"1","Content-Type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},content=response.content)
            assert uploaded.status_code==202
            jobs[zone]=uploaded.json()
            q=QdrantClient(":memory:");q.create_collection("test",vectors_config=VectorParams(size=3,distance=Distance.COSINE))
            schema="numeric_test_"+uuid.uuid4().hex;numeric_schemas.append(schema)
            raw=os.environ["TEST_TIMESCALE_URL"]
            with psycopg.connect(raw) as c:c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            def numeric_connection(schema=schema):return psycopg.connect(raw,options="-csearch_path="+schema)
            ddl=Path("/migration/20261007_csit_numeric_v1.sql").read_text().replace("source_system='CSIT'","source_system='KM_DEV_UPLOAD'").replace("create_hypertable('km_csit_numeric_points'","public.create_hypertable('"+schema+".km_csit_numeric_points'")
            with numeric_connection() as c:c.execute(ddl)
            writers={"storage":StorageWriter(z.settings.storage_root),
                "qdrant":QdrantWriter(q,"test",lambda texts:[[1,.5,.2] for _ in texts],1000),
                "neo4j":Neo4jWriter(driver,"neo4j",DEV_GRAPH_IDENTIFIERS,DEV_GRAPH_CONSTRAINTS),"timescale":TimescaleWriter(numeric_connection)}
            rules=json.loads(Path("/config/csit-integration-v1.numeric-rules.json").read_text())
            pipeline=DevPipeline(z.settings,z.repo,z.local,writers,rules)
            worker=Worker(z.settings,z.repo,z.local,pipeline)
            assert worker.process_one()
            job=z.repo.get(jobs[zone]["jobId"]);assert job["status"]=="Completed"
            assert set(job["storage_references"])=={"Storage","Qdrant","Neo4j","TimescaleDB"}
            payloads=[p.payload for p in q.scroll("test",limit=50)[0]]
            assert all(p["source_system"]=="KM_DEV_UPLOAD" and p["lineage"]["dataZone"]==zone for p in payloads)
            assert any(zone.upper()+"_ONLY_isolation1" in p["content"] for p in payloads)
            assert not any(("TEST" if zone=="da40" else "DA40")+"_ONLY_isolation1" in p["content"] for p in payloads)
            with numeric_connection() as c:
                assert c.execute("SELECT count(*) FROM km_csit_numeric_points WHERE source_system='KM_DEV_UPLOAD'").fetchone()[0]==1
            with z.repo.connect() as c:
                assert c.execute("SELECT count(*) AS n FROM km_csit_callback_deliveries").fetchone()["n"]==0
            assert worker.callback_one() is False
            original=z.local.source(job);original.write_bytes(b"MZ changed")
            with pytest.raises(Exception):z.local.download(job,Path(z.settings.storage_root)/"invalid.txt")
            q.close()
    finally:
        driver.close()
        for schema in numeric_schemas:
            with psycopg.connect(os.environ["TEST_TIMESCALE_URL"]) as c:c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

@pytest.mark.parametrize("account,zone,allowed",[("da40only","da40",True),("da40only","test",False),("testonly","test",True),("testonly","da40",False)])
def test_zone_only_account_current_grants(zones,account,zone,allowed):
    class RestrictedControl:
        def validate_entry_claims(self,sub,data_zone,role,epoch):
            grants={"da40only":{"da40"},"testonly":{"test"}}
            if data_zone not in grants.get(sub,set()):raise ControlAuthorizationError("no grant")
        def get_user(self,sub):return SimpleNamespace(user_id=sub,username=sub)
    auth=EntryAuthenticator(zone,RestrictedControl(),[account])
    cookie=issue_entry_session(account,zone,"user",1)
    if allowed:assert auth(cookie)["username"]==account
    else:
        with pytest.raises(HTTPException) as e:auth(cookie)
        assert e.value.status_code==401

def test_graph_identifiers_reject_injection():
    with pytest.raises(ValueError):Neo4jWriter(None,"neo4j",{"CsitKnowledgeEntity":"unsafe` label"})

def test_same_document_different_owners(zones):
    z=zones["da40"];one=upload(z,b"owner one").json()
    z.client.cookies.set("km_entry_session",issue_entry_session("u2","da40","user",1))
    response=upload(z,b"owner two");assert response.status_code==202
    assert response.json()["jobId"]!=one["jobId"]
    assert z.client.get("/api/dev-upload/jobs/"+one["jobId"]).status_code==404
