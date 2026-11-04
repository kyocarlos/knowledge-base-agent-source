import json,time
from src.web_api.rca_routes import CeleryTasks,default_connect,default_roles,create_router
from fastapi import FastAPI
from fastapi.testclient import TestClient
with default_connect() as c:
    ids=[r[0] for r in c.execute("select test_run_id from km_test.test_run where report_type='wifi_throughput' and product_id like 'TP-Link%%' order by product_id",)]
print("runs:",ids)
# through the real HTTP layer (identity injected), real Celery queue, real worker and model
app=FastAPI()
@app.middleware("http")
async def ident(request,call_next):
    request.state.km_identity={"sub":"verify-user","instance_id":"test"};return await call_next(request)
app.include_router(create_router())
cl=TestClient(app)
print("status:",cl.get("/api/rca/v1/status").json())
r=cl.post("/api/rca/v1/analyze",json={"run_ids":ids,"question":"兩台 TP-Link 的 5GHz 吞吐量差異可能是什麼原因?"});print("submit:",r.status_code,r.json())
tid=r.json()["task_id"];t0=time.time()
while time.time()-t0<300:
    d=cl.get("/api/rca/v1/analyze/"+tid).json()
    if d["status"]!="running":break
    time.sleep(3)
print("waited %.0fs"%(time.time()-t0),"status:",d["status"])
rc=d.get("rca") or {}
print("rca.status:",rc.get("status"),"attempts:",rc.get("attempts"))
print("violations:",rc.get("violations"));print("warnings:",rc.get("warnings"))
a=rc.get("analysis")
if a:
    print("summary:",a["summary"][:200]);print("observations:",len(a["observations"]),"hypotheses:",[(h["cause"][:40],h["confidence"]) for h in a["hypotheses"]]);print("data_gaps:",[g[:60] for g in a["data_gaps"]])
# another user cannot read it
app2=FastAPI()
@app2.middleware("http")
async def ident2(request,call_next):
    request.state.km_identity={"sub":"someone-else","instance_id":"test"};return await call_next(request)
app2.include_router(create_router())
print("other user ->",TestClient(app2).get("/api/rca/v1/analyze/"+tid).status_code)
