from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import pytest
from src.csit_integration_v1.models import IngestionRequest
from src.csit_integration_v1.errors import IntegrationError,LeaseLost
from src.csit_integration_v1.api import ROUTE,create_app
from fastapi.testclient import TestClient

AUTH={"Authorization":"Bearer test-service"}
def test_valid_202(api,payload):
    r=api.post(ROUTE,json=payload,headers=AUTH)
    assert r.status_code==202
    assert r.json()["status"]=="Accepted" and r.json()["documentId"]==payload["documentId"]
@pytest.mark.parametrize("field,value",[
 ("eventId",""),("eventType","AttachmentCommitted"),("sourceSystem","OTHER"),("version",0),
 ("version",-1),("version",True),("version","3"),("documentId",""),("committedAt","bad"),("committedAt","2026-10-07T08:30:00")])
def test_invalid_contract(api,payload,field,value):
    payload[field]=value
    assert api.post(ROUTE,json=payload,headers=AUTH).status_code==422
@pytest.mark.parametrize("mutation",[{"project":None},{"task":{}},{"case":{"id":"x","number":"x"}},{"unknown":"physical-path"}])
def test_malformed(api,payload,mutation):
    payload.update(mutation);assert api.post(ROUTE,json=payload,headers=AUTH).status_code==422
@pytest.mark.parametrize("name",["../report.txt","..\\report.txt","/tmp/report.txt","C:report.txt","report.txt\x00",".","report.txt "])
def test_path_traversal(api,payload,name):
    payload["document"]["fileName"]=name
    assert api.post(ROUTE,json=payload,headers=AUTH).status_code==422
@pytest.mark.parametrize("headers", [{},{"Cookie":"km_control_session=human-session"},{"Authorization":"Bearer test-human"}])
def test_unauthenticated_human_blocked(api,payload,headers):
    assert api.post(ROUTE,json=payload,headers=headers).status_code==401
def test_wrong_scope(api,payload):
    assert api.post(ROUTE,json=payload,headers={"Authorization":"Bearer test-wrong-scope"}).status_code==403
def test_disabled_no_anonymous(repo,settings,payload):
    from conftest import TestTokenValidator
    a=TestClient(create_app(replace(settings,enabled=False),repo,TestTokenValidator()))
    assert a.post(ROUTE,json=payload).status_code==401
    assert a.post(ROUTE,json=payload,headers=AUTH).status_code==503
def test_same_source_retry(api,repo,payload):
    jobs=[]
    for i in range(10):
        payload["eventId"]="retry-"+str(i)
        jobs.append(api.post(ROUTE,json=payload,headers=AUTH).json()["jobId"])
    assert len(set(jobs))==1
    with repo.connect() as c:assert c.execute("SELECT count(*) FROM km_csit_ingestion_jobs").fetchone()["count"]==1
def test_concurrent_duplicate_posts(api,repo,payload):
    with ThreadPoolExecutor(max_workers=12) as pool:
        responses=list(pool.map(lambda _:api.post(ROUTE,json=payload,headers=AUTH),range(20)))
    assert all(r.status_code==202 for r in responses)
    assert len({r.json()["jobId"] for r in responses})==1
def test_metadata_conflict(repo,payload):
    repo.submit(IngestionRequest(**payload))
    payload["document"]["sizeBytes"]+=1
    with pytest.raises(IntegrationError,match="SOURCE_VERSION_CONFLICT"):repo.submit(IngestionRequest(**payload))
def test_versions_preserved(repo,payload):
    first=repo.submit(IngestionRequest(**payload))
    payload["version"]=4
    second=repo.submit(IngestionRequest(**payload))
    assert first["job_id"]!=second["job_id"] and repo.get(first["job_id"])["version"]==3
def test_concurrent_claim(repo,payload):
    repo.submit(IngestionRequest(**payload))
    with ThreadPoolExecutor(max_workers=8) as pool:claimed=list(pool.map(lambda i:repo.claim(str(i),60),range(8)))
    assert sum(x is not None for x in claimed)==1
def test_restart_lease_fencing(repo,payload):
    repo.submit(IngestionRequest(**payload))
    old=repo.claim("crashed",60)
    with repo.connect() as c:c.execute("UPDATE km_csit_ingestion_jobs SET lease_until=clock_timestamp()-interval '1 second'")
    new=repo.claim("restarted",60)
    assert new["job_id"]==old["job_id"] and new["lease_token"]!=old["lease_token"]
    with pytest.raises(LeaseLost):repo.finish(old,{},"p","e")
    repo.renew(new,60)
    repo.checkpoint(new,"Parsing",{"ok":True})
    assert repo.checkpoints(new)["Parsing"]["ok"]
def test_db_uniqueness(repo,payload):
    r=repo.submit(IngestionRequest(**payload))
    with repo.connect() as c:
        constraints=c.execute("SELECT constraint_type FROM information_schema.table_constraints WHERE table_name='km_csit_ingestion_jobs' AND table_schema=current_schema()").fetchall()
    assert any(x["constraint_type"]=="UNIQUE" for x in constraints)
def test_request_size_limit(api):
    assert api.post(ROUTE,content=b"x"*70000,headers=AUTH).status_code==413
