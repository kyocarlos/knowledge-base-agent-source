import json,os
import psycopg,pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.web_api.rca_routes import create_router
from test_report_compare import conn,seeded,add_run,add_m,ROLES  # noqa: F401  (fixtures)

pytestmark=pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),reason="TEST_DATABASE_URL not set")

class InlineTasks:
    """Runs the analysis at submit time in-process and keeps the result, like the Celery worker would, so owner checks and states can be tested."""
    def __init__(self,llm,roles):self.llm,self.roles,self.done,self.n,self.hold=llm,roles,{},0,False
    def submit(self,run_ids,question,owner):
        from src.report_numeric import rca_service,compare
        self.n+=1;tid="t%d"%self.n
        if self.hold:return tid                      # simulates a task that has not finished yet
        try:
            r=rca_service.analyze(lambda:psycopg.connect(os.environ["TEST_DATABASE_URL"],autocommit=True),self.roles,self.llm,run_ids,question)
            self.done[tid]={"owner":owner,"status":"done",**r}
        except compare.CompareError as e:self.done[tid]={"owner":owner,"status":"failed","detail":str(e)}
        return tid
    def fetch(self,tid):return self.done.get(tid)

def client(llm=None,roles=None,identity=True,sub="u1",tasks=None):
    app=FastAPI()
    @app.middleware("http")
    async def ident(request,call_next):
        if identity:request.state.km_identity={"sub":sub,"instance_id":"csit"}
        return await call_next(request)
    q=tasks or (InlineTasks(llm,roles or ROLES) if llm else None)
    app.include_router(create_router(connect=lambda:psycopg.connect(os.environ["TEST_DATABASE_URL"],autocommit=True),tasks=q,roles=lambda:roles or ROLES))
    c=TestClient(app);c.tasks=q
    return c

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

def _wait(c,tid,hdr=None):
    return c.get("/api/rca/v1/analyze/"+tid).json()

def test_analyze_is_submit_then_poll_and_only_the_asker_can_read_it(seeded):
    from test_report_rca import good
    from src.report_numeric import compare
    pack=compare.compare_runs(compare.load_runs(seeded,["A","B"],ROLES),compare.load_directions(seeded))
    c=client(llm=lambda m:json.dumps(good(pack),ensure_ascii=False))
    sub=c.post("/api/rca/v1/analyze",json={"run_ids":["A","B"],"question":"為什麼 ch36 變慢"})
    assert sub.status_code==202 and sub.json()["status"]=="submitted"
    done=_wait(c,sub.json()["task_id"])
    assert done["status"]=="done" and done["rca"]["status"]=="ok" and done["pack"]["diffs"] and "owner" not in done
    other=client(llm=lambda m:"x",sub="someone-else",tasks=c.tasks)
    assert other.get("/api/rca/v1/analyze/"+sub.json()["task_id"]).status_code==404     # a finished analysis belongs to its asker

def test_a_pending_task_reports_running_and_bad_selections_fail_before_queueing(seeded):
    c=client(llm=lambda m:"{}");c.tasks.hold=True
    tid=c.post("/api/rca/v1/analyze",json={"run_ids":["A","B"]}).json()["task_id"]
    assert _wait(c,tid)=={"status":"running"}
    n=c.tasks.n
    assert c.post("/api/rca/v1/analyze",json={"run_ids":["A","NOPE"]}).status_code==422
    assert c.tasks.n==n                                                                   # nothing was queued

def test_model_rejection_and_outage_keep_the_comparison(seeded):
    rejected=client(llm=lambda m:"I think it is the firmware")
    d=_wait(rejected,rejected.post("/api/rca/v1/analyze",json={"run_ids":["A","B"]}).json()["task_id"])
    assert d["status"]=="done" and d["rca"]["status"]=="rejected" and d["rca"]["analysis"] is None and d["pack"]["diffs"]
    def boom(m):raise RuntimeError("llm down")
    down=client(llm=boom)
    d=_wait(down,down.post("/api/rca/v1/analyze",json={"run_ids":["A","B"]}).json()["task_id"])
    assert d["rca"]["status"]=="unavailable" and d["pack"]["diffs"]

def test_analysis_can_be_switched_off_while_comparison_stays(seeded):
    c=client()                                       # no task queue configured, KM_RCA_ANALYZE unset
    assert c.get("/api/rca/v1/status").json()=={"compare":True,"analyze":False}
    assert c.post("/api/rca/v1/analyze",json={"run_ids":["A","B"]}).status_code==503
    assert c.post("/api/rca/v1/compare",json={"run_ids":["A","B"]}).status_code==200

def test_runs_describe_formula_errors_by_sheet(seeded):
    import json as _j
    seeded.execute("INSERT INTO km_test.report_package(package_id,document_id,document_version,test_run_id,content_hash,quality) VALUES('p-A','DOC-A','1','A','h',%s)",
        (_j.dumps({"formula_errors":[{"sheet":"4.3 Concurrent Test","cell":"I9","value":"#REF!","sheet_state":"hidden"},{"sheet":"4.3 Concurrent Test","cell":"I10","value":"#REF!","sheet_state":"hidden"},
                                      {"sheet":"3.1 RvR","cell":"Z21","value":"#DIV/0!","sheet_state":"visible"}]}),))
    runs={r["test_run_id"]:r for r in client().get("/api/rca/v1/runs").json()["runs"]}
    summary=runs["A"]["error_summary"]
    assert [(s["sheet"],s["hidden"],s["count"],s["values"]) for s in summary]==[("3.1 RvR",False,1,["#DIV/0!"]),("4.3 Concurrent Test",True,2,["#REF!"])]
    assert runs["B"]["error_summary"]==[]

def test_missing_database_setting_is_a_503_for_rca_only(monkeypatch):
    for k in ("KM_RCA_DSN","KM_RCA_DSN_FILE"):monkeypatch.delenv(k,raising=False)
    monkeypatch.setenv("KM_RCA_ENABLED","1")
    app=FastAPI()
    @app.middleware("http")
    async def ident(request,call_next):
        request.state.km_identity={"sub":"u1"};return await call_next(request)
    app.include_router(create_router())          # building the router must not need the database setting
    r=TestClient(app).get("/api/rca/v1/runs")
    assert r.status_code==503 and "not available" in r.json()["detail"]

def test_disabled_by_default_even_when_registered(monkeypatch):
    monkeypatch.delenv("KM_RCA_ENABLED",raising=False)
    app=FastAPI()
    @app.middleware("http")
    async def ident(request,call_next):
        request.state.km_identity={"sub":"u1"};return await call_next(request)
    app.include_router(create_router())
    assert TestClient(app).get("/api/rca/v1/runs").status_code==503

def _main_app_paths(env):
    """Import the real application in a fresh interpreter so the module-level registration runs with the given environment."""
    import subprocess,sys,json as _json
    code="import json;from src.web_api import app;print(json.dumps(sorted(p for p in app.openapi()['paths'] if 'rca' in p)))"
    out=subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,env={**os.environ,"PYTHONPATH":".",**env},timeout=120)
    assert out.returncode==0,out.stderr[-800:]
    return _json.loads(out.stdout.strip().splitlines()[-1])

def test_the_main_app_only_registers_rca_when_enabled():
    assert _main_app_paths({"KM_RCA_ENABLED":"0"})==[]    # default: the application is exactly what it was
    on=_main_app_paths({"KM_RCA_ENABLED":"1"})
    assert "/api/rca/v1/runs" in on and "/api/rca/v1/compare" in on and "/api/rca/v1/analyze" in on

def test_the_celery_task_is_registered_and_answers_without_a_model_or_store():
    import subprocess,sys
    code=("from src.web_api import rca_tasks;from src.web_api.tasks import celery_app;import json;"
          "print('tasks.rca_analyze_task' in celery_app.tasks);"
          "print(json.dumps(rca_tasks.rca_analyze_task.run(['a','b'],'',{'user_id':'u'}),ensure_ascii=False))")
    env={k:v for k,v in os.environ.items() if k not in ("KM_RCA_DSN","KM_RCA_DSN_FILE")}
    out=subprocess.run([sys.executable,"-c",code],capture_output=True,text=True,env={**env,"PYTHONPATH":"."},timeout=120)
    assert out.returncode==0,out.stderr[-600:]
    lines=out.stdout.strip().splitlines()
    assert lines[-2]=="True"
    r=json.loads(lines[-1]);assert r["status"]=="failed" and r["owner"]=={"user_id":"u"} and "ProblemError" not in r["detail"]   # a missing store never leaks details
