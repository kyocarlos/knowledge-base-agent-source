import json,os
import psycopg,pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.web_api.rca_routes import create_router
from test_report_compare import conn,seeded,add_run,add_m,ROLES  # noqa: F401  (fixtures)

pytestmark=pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),reason="TEST_DATABASE_URL not set")

def client(llm=None,roles=None,identity=True):
    app=FastAPI()
    @app.middleware("http")
    async def ident(request,call_next):
        if identity:request.state.km_identity={"sub":"u1","instance_id":"csit"}
        return await call_next(request)
    app.include_router(create_router(connect=lambda:psycopg.connect(os.environ["TEST_DATABASE_URL"],autocommit=True),llm_factory=(lambda:llm) if llm else None,
                                     roles=lambda:roles or ROLES))
    return TestClient(app)

def test_login_is_required(seeded):
    assert client(identity=False).get("/api/rca/v1/runs").status_code==401
    assert client(identity=False).post("/api/rca/v1/compare",json={"run_ids":["A","B"]}).status_code==401

def test_list_runs_is_role_filtered_and_searchable(seeded):
    r=client().get("/api/rca/v1/runs").json()
    assert {x["test_run_id"] for x in r["runs"]}=={"A","B","C"}
    assert client(roles=["OTHER"]).get("/api/rca/v1/runs").json()["runs"]==[]
    assert client().get("/api/rca/v1/runs",params={"product":"NOPE"}).json()["runs"]==[]

def test_compare_returns_the_pack_and_explains_bad_selections(seeded):
    ok=client().post("/api/rca/v1/compare",json={"run_ids":["A","B"]})
    assert ok.status_code==200 and ok.json()["counts"]["notable"]>=1 and ok.json()["evidence"]
    assert client().post("/api/rca/v1/compare",json={"run_ids":["A","NOPE"]}).status_code==422
    assert client().post("/api/rca/v1/compare",json={"run_ids":["A"]}).status_code==422
    assert client(roles=["OTHER"]).post("/api/rca/v1/compare",json={"run_ids":["A","B"]}).status_code==422

def test_analyze_returns_pack_with_a_verified_analysis_or_a_rejection(seeded):
    from test_report_rca import good
    from src.report_numeric import compare
    pack=compare.compare_runs(compare.load_runs(seeded,["A","B"],ROLES),compare.load_directions(seeded))
    ok=client(llm=lambda m:json.dumps(good(pack),ensure_ascii=False)).post("/api/rca/v1/analyze",json={"run_ids":["A","B"],"question":"為什麼 ch36 變慢"})
    assert ok.status_code==200 and ok.json()["rca"]["status"]=="ok" and ok.json()["pack"]["diffs"]
    rejected=client(llm=lambda m:"I think it is the firmware").post("/api/rca/v1/analyze",json={"run_ids":["A","B"]}).json()
    assert rejected["rca"]["status"]=="rejected" and rejected["rca"]["analysis"] is None and rejected["pack"]["diffs"]   # the comparison survives
    def boom(m):raise RuntimeError("llm down")
    down=client(llm=boom).post("/api/rca/v1/analyze",json={"run_ids":["A","B"]}).json()
    assert down["rca"]["status"]=="unavailable" and down["pack"]["diffs"]
