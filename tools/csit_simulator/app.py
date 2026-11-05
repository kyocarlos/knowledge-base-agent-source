"""HTTP surface of the simulator: the CSIT-facing routes KM calls, plus the /api/* routes the UI uses."""
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import HTMLResponse,JSONResponse
from .sim import Sim,BASE,TAXONOMY

def create_app(sim:Sim)->FastAPI:
    app=FastAPI(title="CSIT 模擬器",docs_url="/docs")
    async def body(request):
        try:return await request.json()
        except ValueError:raise HTTPException(400,"body is not JSON") from None

    # ----- what KM calls on CSIT -----
    @app.get(BASE+"/document-library/files/{file_id}/content")
    def content(file_id:str,request:Request):return sim.serve_file(request,file_id)
    @app.post(BASE+"/document-library/ingestion-status")
    async def ingestion(request:Request):return sim.receive(request,await body(request),"ingestion")
    @app.post(BASE+"/document-deletion-status")
    async def deletion(request:Request):return sim.receive(request,await body(request),"deletion")

    # ----- the identity authority KM trusts (only when the simulator was started with --identity) -----
    if sim.identity is not None:
        @app.get("/.well-known/jwks")
        def jwks():return sim.identity.jwks()
        @app.post("/oauth/token")
        async def token(request:Request):
            status,payload=sim.identity.token_endpoint(request.headers.get("authorization",""),await request.body())
            sim.log("KM→CSIT-IdP","POST","/oauth/token",status,None,{k:v for k,v in payload.items() if k!="access_token"},None,None,"client credentials")
            return JSONResponse(payload,status_code=status,headers={"Cache-Control":"no-store"})

    # ----- what the UI does -----
    @app.get("/api/taxonomy")
    def taxonomy():return TAXONOMY
    @app.get("/api/state")
    def state():return sim.state()
    @app.get("/api/report")
    def report():return sim.report()
    @app.get("/api/traffic")
    def traffic(after:int=0):return sim.traffic_since(after)
    @app.post("/api/docs")
    async def new_doc(request:Request):return sim.create_doc(await body(request))
    @app.post("/api/docs/{doc_id}/approve")
    def approve(doc_id:str):return sim.approve(doc_id)
    @app.post("/api/docs/{doc_id}/reject")
    def reject(doc_id:str):return sim.reject(doc_id)
    @app.post("/api/docs/{doc_id}/archive")
    def archive(doc_id:str):return sim.archive(doc_id)
    @app.post("/api/docs/{doc_id}/advance")
    def advance(doc_id:str):return sim.advance(doc_id)
    @app.post("/api/docs/{doc_id}/run-all")
    def run_all(doc_id:str):return sim.run_all(doc_id)
    @app.post("/api/docs/{doc_id}/dispatch")
    async def dispatch(doc_id:str,request:Request):
        raw=await request.body();d={}
        if raw:d=await body(request)
        return sim.dispatch(doc_id,bool(d.get("newJob")))
    @app.post("/api/docs/{doc_id}/faults")
    async def faults(doc_id:str,request:Request):return sim.set_faults(doc_id,await body(request))
    @app.post("/api/docs/{doc_id}/delete")
    async def delete(doc_id:str,request:Request):
        raw=await request.body();d={}
        if raw:d=await body(request)
        return sim.delete(doc_id,d.get("deletionRequestId"))
    @app.post("/api/callback-faults")
    async def callback_faults(request:Request):
        d=await body(request)
        with sim.lock:sim.faults.update({k:int(d[k]) for k in ("callbackFailures","callbackStatus") if k in d})
        return sim.faults
    @app.post("/api/settings")
    async def settings(request:Request):
        d=await body(request);sim.configure(d.get("kmBaseUrl"),d.get("token"));return sim.state()["settings"]
    @app.get("/api/km/ping")
    def ping():return sim.ping()
    @app.get("/api/km/inspect")
    def inspect():
        if sim.inspect is None:raise HTTPException(404,"KM inspection is only available in the local demo")
        return sim.inspect()
    @app.post("/api/reset")
    def reset():sim.reset();return {"ok":True}
    @app.get("/",response_class=HTMLResponse)
    def ui():return (Path(__file__).parent/"ui.html").read_text(encoding="utf-8")
    return app
