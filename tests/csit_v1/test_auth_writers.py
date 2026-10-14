from dataclasses import replace
from pathlib import Path
import json,os
from types import SimpleNamespace
import pytest,httpx,jwt,psycopg
from cryptography.hazmat.primitives.asymmetric import rsa
from datetime import datetime,timezone,timedelta
from fastapi import HTTPException
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams,Distance
from src.csit_integration_v1.auth import JwtServiceTokenValidator,ClientCredentialsProvider,OUTBOUND_SCOPES
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.models import IngestionRequest
from src.csit_integration_v1.pipeline import Entity,Relation,Metric,lineage
from src.csit_integration_v1.writers import QdrantWriter,Neo4jWriter,TimescaleWriter

@pytest.mark.parametrize("mutation,accepted",[
 ({},True),({"principal_type":"human"},False),({"client_id":"unapproved"},False),
 ({"iss":"https://wrong.invalid/"},False),({"aud":"wrong"},False),
 ({"exp":1},False),({"principal_type":None},False)])
def test_real_signature_service_policy(settings,mutation,accepted):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=datetime.now(timezone.utc)
    claims={"iss":settings.authority,"aud":settings.audience,"iat":now,"exp":now+timedelta(minutes=5),
        "principal_type":"service","client_id":"csit-test","scope":"km.ingestion.submit"}
    claims.update(mutation)
    token=jwt.encode(claims,key,algorithm="RS256",headers={"kid":"test-key"})
    validator=JwtServiceTokenValidator(settings)
    validator.keys=SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=key.public_key()))
    if accepted:assert validator.validate(token).client_id=="csit-test"
    else:
        with pytest.raises(HTTPException):validator.validate(token)
def test_invalid_signature(settings):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=datetime.now(timezone.utc)
    t=jwt.encode({"iss":settings.authority,"aud":settings.audience,"iat":now,"exp":now+timedelta(minutes=1),
        "principal_type":"service","client_id":"csit-test"},other,algorithm="RS256")
    v=JwtServiceTokenValidator(settings);v.keys=SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=key.public_key()))
    with pytest.raises(HTTPException):v.validate(t)
def test_outbound_token_cache_and_scopes(settings):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    now=datetime.now(timezone.utc)
    token=jwt.encode({"iss":settings.authority,"aud":settings.outbound_audience,"iat":now,"exp":now+timedelta(minutes=5),"principal_type":"service","client_id":settings.client_id,"sub":settings.client_id,"scope":" ".join(OUTBOUND_SCOPES)},key,algorithm="RS256")
    calls=[]
    def handler(r):
        calls.append(r)
        assert b"client_credentials" in r.content and all(scope.replace(".",".").encode() in r.content for scope in OUTBOUND_SCOPES)
        return httpx.Response(200,json={"access_token":token,"token_type":"Bearer","expires_in":300,"scope":" ".join(OUTBOUND_SCOPES)})
    provider=ClientCredentialsProvider(settings,httpx.MockTransport(handler))
    provider.keys=SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=key.public_key()))
    assert provider.headers()==provider.headers() and len(calls)==1
    provider.close()
def test_outbound_missing_scope(settings):
    p=ClientCredentialsProvider(settings,httpx.MockTransport(lambda r:httpx.Response(200,json={
        "access_token":"test-only","token_type":"Bearer","expires_in":300,"scope":"csit.document.read"})))
    with pytest.raises(IntegrationError,match="M2M_SCOPE_MISSING"):p.headers()
def test_secret_separation(settings):
    assert settings.client_id!="km-dev" and "/km-oidc/" not in settings.secret_file
    with pytest.raises(ValueError):replace(settings,service_clients=()).validate()

def test_qdrant_real_local_upsert_retry_lineage(payload,repo):
    job=repo.submit(IngestionRequest(**payload));meta=lineage(job)
    q=QdrantClient(":memory:")
    q.create_collection("csit-test",vectors_config=VectorParams(size=3,distance=Distance.COSINE))
    writer=QdrantWriter(q,"csit-test",lambda texts:[[1.,.5,.2] for _ in texts],5)
    first=writer.write("knowledge report",meta,job)
    second=writer.write("knowledge report",meta,job)
    assert first==second and q.count("csit-test",exact=True).count==len(first["pointIds"])
    points=q.retrieve("csit-test",ids=first["pointIds"])
    assert all(p.payload["lineage"]==meta and p.payload["content"] and p.payload["metadata"]==meta for p in points)
    assert all(p.payload["project_code"]==payload["project"]["number"] for p in points)
    assert all(p.payload["lineage"]["task"]["number"]==payload["task"]["number"] for p in points)
    meta2=dict(meta,version=4)
    writer.write("knowledge report",meta2,dict(job,version=4))
    assert q.count("csit-test",exact=True).count==2*len(first["pointIds"])
def test_neo4j_real_concurrent_upsert(payload,repo):
    from neo4j import GraphDatabase
    from concurrent.futures import ThreadPoolExecutor
    job=repo.submit(IngestionRequest(**payload));meta=lineage(job)
    driver=GraphDatabase.driver(os.environ["TEST_NEO4J_URI"],auth=None)
    with driver.session(database="neo4j") as s:
        for statement in Path(__file__).resolve().parents[2].joinpath("migrations/20261007_csit_graph_v1.cypher").read_text().split(";"):
            if statement.strip():s.run(statement).consume()
    w=Neo4jWriter(driver,"neo4j")
    items=([Entity(key="a",kind="DUT",name="Device"),Entity(key="b",kind="Issue",name="Timeout")],
        [Relation(source="a",target="b",kind="HAS_ISSUE")])
    with ThreadPoolExecutor(max_workers=4) as p:list(p.map(lambda _:w.write(items,meta,job),range(8)))
    with driver.session(database="neo4j") as s:
        count=s.run("MATCH (r:CsitKnowledgeRelation) WHERE r.lineage=$lineage RETURN count(r) AS n",
            lineage=json.dumps(meta,ensure_ascii=False,sort_keys=True)).single()["n"]
        assert count==1
        edges=s.run("MATCH ()-[r:CSIT_RELATION_SOURCE]->(n:CsitKnowledgeRelation) WHERE n.lineage=$lineage RETURN count(r) AS n",
            lineage=json.dumps(meta,ensure_ascii=False,sort_keys=True)).single()["n"]
        assert edges==1
    driver.close()
def test_timescale_real_retry_no_duplicates(payload,repo):
    raw=os.environ["TEST_TIMESCALE_URL"]
    with psycopg.connect(raw) as c:c.execute(Path(__file__).resolve().parents[2].joinpath("migrations/20261007_csit_numeric_v1.sql").read_text())
    job=repo.submit(IngestionRequest(**payload));meta=lineage(job)
    metric=Metric(key="row1",timestamp=datetime.now(timezone.utc),metric="iperf",value=125.5,unit="Mbit/s")
    writer=TimescaleWriter(lambda:psycopg.connect(raw))
    writer.write([metric],meta,job);writer.write([metric],meta,job)
    with psycopg.connect(raw) as c:
        assert c.execute("SELECT count(*) FROM km_csit_numeric_points WHERE document_id=%s",(meta["documentId"],)).fetchone()[0]==1
        assert c.execute("SELECT lineage FROM km_csit_numeric_points WHERE document_id=%s",(meta["documentId"],)).fetchone()[0]==meta
        assert c.execute("SELECT count(*) FROM timescaledb_information.hypertables WHERE hypertable_name='km_csit_numeric_points'").fetchone()[0]==1
def test_numeric_schema_nan_rejected():
    with pytest.raises(ValueError):Metric(key="r",timestamp=datetime.now(timezone.utc),metric="kpi",value=float("nan"),unit="percent")
