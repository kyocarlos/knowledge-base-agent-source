from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.web_api.rca_routes import create_router
app=FastAPI()
@app.middleware("http")
async def ident(request,call_next):
    request.state.km_identity={"sub":"verify"};return await call_next(request)
app.include_router(create_router())
c=TestClient(app)
r=c.get("/api/rca/v1/runs");j=r.json();print("runs",r.status_code,len(j["runs"]),j["report_types"])
ids=[x["test_run_id"] for x in j["runs"] if x["report_type"]=="wifi_rvr"][:3]
r=c.post("/api/rca/v1/compare",json={"run_ids":ids});p=r.json();print("compare rvr x3",r.status_code,p["counts"],"factors",len(p["factors"]),"top",p["diffs"][0]["label"][:60])
r=c.post("/api/rca/v1/compare",json={"run_ids":[ids[0],j["runs"][0]["test_run_id"]]});print("mixed/other",r.status_code,str(r.json())[:90])
r=c.post("/api/rca/v1/compare",json={"run_ids":["nope","nada"]});print("unknown",r.status_code,r.json())
r=c.get("/api/rca/v1/runs",params={"product":"BE80"});print("search BE80",len(r.json()["runs"]))
