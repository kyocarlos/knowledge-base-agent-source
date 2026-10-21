import asyncio,hashlib,json,re,uuid
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse,StreamingResponse
from src.csit_integration_v1.models import safe_filename
from src.csit_integration_v1.pipeline import validate_file
from src.csit_integration_v1.errors import IntegrationError
from .repository import public_job

REF=re.compile(r"^[A-Za-z0-9_-]{1,64}$")
def ref(value):
    if not isinstance(value,str) or not REF.fullmatch(value):raise HTTPException(422,"Use 1–64 letters, digits, underscore or hyphen for test references")
    return value

def create_app(settings,repo,local,authenticate,origins,zone,enabled=True,runner=None,evidence=None,search=None):
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    @app.middleware("http")
    async def guard(request,call_next):
        if request.url.path=="/health":return JSONResponse({"status":"ok","dataZone":zone,"devUploadEnabled":enabled,"csitCallbackEnabled":False})
        if request.url.path=="/dev-chat-bridge.js":
            response=await call_next(request)
            response.headers["Cache-Control"]="no-store"
            response.headers["X-Content-Type-Options"]="nosniff"
            return response
        if not enabled:return JSONResponse({"detail":"DEV upload disabled"},status_code=404)
        try:
            user=await asyncio.to_thread(authenticate,request.cookies.get("km_entry_session",""))
            request.state.user=user
        except HTTPException as e:
            if request.url.path=="/dev-upload.html":
                return HTMLResponse('<!doctype html><meta charset="utf-8"><h2>請先登入 KM 並選擇 DA40 或 TEST</h2><a href="/login.html">前往 KM 登入／資料區選擇</a>',status_code=e.status_code)
            return JSONResponse({"detail":e.detail},status_code=e.status_code)
        except Exception:return JSONResponse({"detail":"KM authorization unavailable"},status_code=503)
        if request.method not in ("GET","HEAD"):
            if request.headers.get("origin") not in origins or request.headers.get("x-km-dev-upload")!="1":
                return JSONResponse({"detail":"Same-origin DEV upload request required"},status_code=403)
        response=await call_next(request)
        response.headers["Cache-Control"]="no-store"
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="same-origin"
        return response
    @app.exception_handler(Exception)
    async def unavailable(request,error):
        return JSONResponse({"detail":"DEV upload service unavailable"},status_code=503)
    @app.exception_handler(IntegrationError)
    async def integration_error(request,error):
        return JSONResponse({"detail":{"code":error.code,"message":error.message}},status_code=409 if error.code=="SOURCE_VERSION_CONFLICT" else 422)
    @app.get("/dev-chat-bridge.js")
    def chat_bridge():
        return FileResponse(Path(__file__).with_name("chat_bridge.js"),media_type="text/javascript")
    @app.get("/dev-upload.html")
    def page():
        response=HTMLResponse(Path(__file__).with_name("page.html").read_text())
        response.headers["Content-Security-Policy"]="default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
        return response
    @app.get("/api/dev-upload/sample")
    def sample(testRunId:str):
        import io
        from openpyxl import Workbook
        run=ref(testRunId);book=Workbook();summary=book.active;summary.title="Report"
        summary.append(["field","value"]);summary.append(["testMarker",zone.upper()+"_ONLY_"+run]);summary.append(["purpose","DEV isolation test report"])
        metrics=book.create_sheet("Metrics");metrics.append(["timestamp","throughput_mbps"])
        metrics.append([datetime.now(timezone.utc).isoformat(),123.5])
        out=io.BytesIO();book.save(out);out.seek(0)
        return StreamingResponse(out,media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition":"attachment; filename=isolation-report.xlsx"})
    @app.get("/api/dev-upload/me")
    def me(request:Request):
        return {"dataZone":zone,"username":request.state.user["username"],"sourceSystem":"KM_DEV_UPLOAD","callbackEnabled":False,"maxFileSize":settings.max_file_size}
    @app.get("/api/dev-upload/jobs")
    def jobs(request:Request):
        return {"jobs":[public_job(r,repo) for r in repo.list_owned(request.state.user["user_id"])]}
    def owned(request,job_id):
        r=repo.owned(job_id,request.state.user["user_id"])
        if not r:raise HTTPException(404,"Job not found in your current data zone")
        return r
    @app.get("/api/dev-upload/jobs/{job_id}")
    def status(request:Request,job_id:str):return public_job(owned(request,job_id),repo)
    @app.get("/api/dev-upload/jobs/{job_id}/file")
    def original(request:Request,job_id:str):
        r=owned(request,job_id)
        return FileResponse(local.source(r),filename=r["file_name"],media_type="application/octet-stream")
    @app.get("/api/dev-upload/jobs/{job_id}/evidence")
    def proof(request:Request,job_id:str):
        r=owned(request,job_id)
        if not evidence:raise HTTPException(503,"Writer readback unavailable")
        return evidence(r)
    @app.get("/api/dev-upload/search")
    def lookup(request:Request,term:str):
        if len(term)<3 or len(term)>128:raise HTTPException(422,"Search term must contain 3–128 characters")
        if not search:raise HTTPException(503,"DEV search unavailable")
        return search(term,request.state.user["user_id"])
    @app.post("/api/dev-upload/jobs",status_code=202)
    async def upload(request:Request):
        allowed={"testRunId","documentId","version","fileName"}
        if set(request.query_params)-allowed:raise HTTPException(422,"Unknown query fields; data zone is selected by the server")
        run=ref(request.query_params.get("testRunId",""))
        doc=ref(request.query_params.get("documentId",""))
        try:
            version=int(request.query_params.get("version","1"))
            if version<1 or version>1000000:raise ValueError()
            filename=safe_filename(request.query_params.get("fileName",""))
            if not 1<=len(filename)<=255:raise ValueError()
        except (ValueError,TypeError):raise HTTPException(422,"Invalid version or filename")
        suffix=Path(filename).suffix.lower()
        types={".txt":"text/plain",".csv":"text/csv",".xlsx":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",".pdf":"application/pdf",".docx":"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        if suffix not in types:raise HTTPException(422,"Supported formats: XLSX, CSV, TXT, PDF, DOCX")
        content_type=request.headers.get("content-type","").split(";")[0].lower()
        if content_type!=types[suffix]:raise HTTPException(422,"Content-Type does not match the report format")
        length=request.headers.get("content-length")
        if length:
            try:
                if int(length)<1:raise HTTPException(422,"Empty report or invalid Content-Length")
                if int(length)>settings.max_file_size:raise HTTPException(413,"File exceeds configured size limit")
            except ValueError:raise HTTPException(422,"Invalid Content-Length")
        reference=uuid.uuid4().hex+suffix;path=local.root/reference
        local.root.mkdir(parents=True,exist_ok=True)
        digest=hashlib.sha256();size=0;kept=False
        try:
            with path.open("xb") as output:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>settings.max_file_size:raise HTTPException(413,"File exceeds configured size limit")
                    digest.update(chunk);output.write(chunk)
            if size==0:raise HTTPException(422,"Empty report")
            await asyncio.to_thread(validate_file,path,{"file_name":filename,"content_type":content_type,"size_bytes":size},settings)
            user=request.state.user
            p={"eventId":uuid.uuid4().hex,"eventType":"KMDevTestUpload","sourceSystem":"KM_DEV_UPLOAD",
               "documentId":zone+":"+user["user_id"]+":"+run+":"+doc,"displayDocumentId":doc,"version":version,
               "document":{"fileName":filename,"contentType":content_type,"sizeBytes":size},
               "committedAt":datetime.now(timezone.utc).isoformat(),"dataZone":zone,"testRunId":run,
               "ownerId":user["user_id"],"uploadReference":reference,"uploadSha256":digest.hexdigest()}
            for key in ("project","case","task"):
                p[key]={"id":zone+":"+run+":"+key,"code":"DEV-"+key.upper(),"name":run+" "+key}
            r,duplicate=await asyncio.to_thread(repo.submit_payload,p)
            kept=not duplicate
            result=await asyncio.to_thread(public_job,r,repo);result["duplicate"]=duplicate
            return result
        finally:
            if not kept:path.unlink(missing_ok=True)
    return app
