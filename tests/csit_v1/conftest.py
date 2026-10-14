import os,uuid,json
from pathlib import Path
from dataclasses import replace
import pytest,psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.repository import Repository
from src.csit_integration_v1.auth import ServiceIdentity
from fastapi import HTTPException

@pytest.fixture(scope="session")
def db_url():
    raw=os.environ["TEST_DATABASE_URL"]
    schema="csit_v1_test_"+uuid.uuid4().hex
    with psycopg.connect(raw) as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    dsn=make_conninfo(raw,options="-c search_path="+schema)
    with psycopg.connect(dsn) as c:
        c.execute(Path(__file__).resolve().parents[2].joinpath("migrations/20261007_csit_integration_v1.sql").read_text())
    with psycopg.connect(dsn) as c:
        c.execute("CREATE TABLE km_users(user_id text PRIMARY KEY,status text NOT NULL,is_admin boolean NOT NULL)")
        c.execute("CREATE TABLE km_audit_events(event_id text PRIMARY KEY,occurred_at bigint NOT NULL,actor_user_id text,target_user_id text,event_type text NOT NULL,detail_json text NOT NULL)")
    yield dsn
    with psycopg.connect(raw) as c:
        c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))

@pytest.fixture
def repo(db_url):
    repository=Repository(db_url)
    with repository.connect() as c:
        c.execute("TRUNCATE km_csit_callback_deliveries,km_csit_phase_checkpoints,km_csit_ingestion_jobs,km_audit_events,km_users")
    return repository

@pytest.fixture
def payload():
    return {"eventId":str(uuid.uuid4()),"eventType":"TestReportCommitted","sourceSystem":"CSIT",
        "documentId":"report-"+uuid.uuid4().hex,"version":3,
        "project":{"id":"p1","number":"PROJECT","name":"Project"},
        "case":{"id":"c1","number":"CASE","name":"Case"},
        "task":{"id":"t1","number":"TASK","name":"Task"},
        "document":{"fileName":"report.txt","contentType":"text/plain","sizeBytes":12},
        "committedAt":"2026-10-07T08:30:00+08:00"}

@pytest.fixture
def settings(db_url,tmp_path):
    secret=tmp_path/"outbound-service-secret";secret.write_text("test-only-outbound");secret.chmod(0o600)
    return Settings(enabled=True,db_url=db_url,csit_base_url="https://fake-csit.invalid",
        authority="https://fake-identity.invalid/",audience="km-test-api",outbound_audience="csit-test-api",
        jwks_uri="https://fake-identity.invalid/jwks",token_url="https://fake-identity.invalid/token",
        client_id="km-integration-test",secret_file=str(secret),service_clients=("csit-test",),
        storage_root=str(tmp_path/"artifacts"),retry_delays=(0,0),callback_retry_delays=(0,0))

class TestTokenValidator:
    def validate(self,token):
        if token=="test-service":return ServiceIdentity("csit-test",frozenset({"km.ingestion.submit"}))
        if token=="test-wrong-scope":return ServiceIdentity("csit-test",frozenset({"unrelated.scope"}))
        raise HTTPException(401,"Not a service identity")

@pytest.fixture
def api(repo,settings):
    from fastapi.testclient import TestClient
    from src.csit_integration_v1.api import create_app
    return TestClient(create_app(settings,repo,TestTokenValidator()))
