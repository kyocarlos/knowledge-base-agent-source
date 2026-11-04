"""CSIT simulator: plays CSIT for KM against CSIT x AI KM spec v1.3.

Outbound (CSIT -> KM): document-library/jobs and document-deletions.
Inbound  (KM -> CSIT): file download, document-library/ingestion-status, document-deletion-status.
Every KM behaviour is judged against the spec and recorded as a verdict; nothing here talks to a CSIT database.
"""
import base64,hashlib,json,threading,time,uuid
from datetime import datetime,timezone
from pathlib import Path
import httpx
from fastapi import FastAPI,HTTPException,Request,Response
from fastapi.responses import HTMLResponse
from .checks import check_ingestion_callback,check_deletion_callback

BASE="/api/integrations/km/v1"
def now():return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")

class Sim:
    def __init__(self,km_base_url,token,timeout=15):
        self.km=km_base_url.rstrip("/");self.token=token;self.timeout=timeout
        self.lock=threading.RLock()
        self.reset()
    def reset(self):
        with self.lock:
            self.jobs={};self.dels={};self.seen_callbacks={};self.violations=[];self.global_faults={"callbackFailures":0,"callbackStatus":503}
    # ---------- helpers ----------
    def ev(self,obj,kind,detail=None):obj["timeline"].append({"t":now(),"kind":kind,"detail":detail})
    def verdict(self,obj,ok,what):
        obj["verdicts"].append({"ok":ok,"what":what})
        if not ok:self.violations.append({"ref":obj.get("kmJobId") or obj.get("csitJobId") or obj.get("deletionRequestId"),"what":what})
    def _headers(self,key,bad):
        return {"Authorization":"Bearer "+("not-the-real-token" if bad else self.token),"Idempotency-Key":key,"Content-Type":"application/json"}
    def _auth_ok(self,request):
        return request.headers.get("authorization")=="Bearer "+self.token

    # ---------- CSIT -> KM ----------
    def create_job(self,spec):
        content=base64.b64decode(spec["contentBase64"]) if spec.get("contentBase64") else spec.get("contentText","").encode()
        sha=hashlib.sha256(content).hexdigest()
        job={"csitJobId":spec.get("csitJobId") or str(uuid.uuid4()),"documentFileId":spec.get("documentFileId") or str(uuid.uuid4()),
             "fileName":spec.get("fileName","document.txt"),"content":content,"sha256":spec.get("declaredSha256") or sha,
             "declaredSize":spec.get("declaredSize",len(content)),"contentType":spec.get("contentType","text/plain"),
             "classification":spec.get("classification") or {"l1":{"id":"1","name":"Equipment"},"l2":{"id":"2","name":"Wi-Fi"},"l3":None},
             "faults":{"download":spec.get("downloadFault","none"),"downloadFailures":int(spec.get("downloadFailures",0)),
                       "badToken":bool(spec.get("badToken")),"noIdempotencyKey":bool(spec.get("noIdempotencyKey"))},
             "state":"New","kmJobId":None,"callbacks":[],"downloads":[],"verdicts":[],"timeline":[],"deleted":False,"sendCount":0}
        with self.lock:self.jobs[job["csitJobId"]]=job
        return self.send_job(job["csitJobId"])
    def send_job(self,csit_job_id):
        job=self.jobs[csit_job_id]
        body={"schemaVersion":"1.0","sourceSystem":"CSIT","eventType":"DocumentLibraryFileUploaded","documentFileId":job["documentFileId"],
              "csitJobId":job["csitJobId"],"occurredAt":now(),
              "file":{"originalFileName":job["fileName"],"standardFileName":job["fileName"],"contentType":job["contentType"],
                      "fileSizeBytes":job["declaredSize"],"sha256":job["sha256"],
                      "downloadUrl":f"{self.km}{BASE}/document-library/files/{job['documentFileId']}/content"},
              "classification":job["classification"]}
        headers=self._headers(job["csitJobId"],job["faults"]["badToken"])
        if job["faults"]["noIdempotencyKey"]:headers.pop("Idempotency-Key")
        job["sendCount"]+=1;self.ev(job,"POST /document-library/jobs",{"attempt":job["sendCount"]})
        try:r=httpx.post(self.km+"/api/integrations/csit/v1/document-library/jobs",json=body,headers=headers,timeout=self.timeout)
        except httpx.HTTPError as e:
            self.ev(job,"send failed",type(e).__name__);self.verdict(job,False,"KM unreachable: "+type(e).__name__);return self.public(job)
        self.ev(job,f"KM answered {r.status_code}",r.text[:300])
        if job["faults"]["badToken"]:
            self.verdict(job,r.status_code==401,"invalid bearer token is rejected with 401 (got %s)"%r.status_code)
        elif r.status_code==202:
            d=r.json()
            ok=d.get("csitJobId")==job["csitJobId"] and d.get("status")=="Accepted" and isinstance(d.get("kmJobId"),str) and d["kmJobId"]
            self.verdict(job,bool(ok),"202 body is {csitJobId,kmJobId,status:Accepted}")
            if job["kmJobId"] and d.get("kmJobId")!=job["kmJobId"]:self.verdict(job,False,"resend returned a different kmJobId (must be idempotent)")
            elif job["kmJobId"]:self.verdict(job,True,"resend returned the original kmJobId")
            job["kmJobId"]=d.get("kmJobId");job["state"]="Accepted"
        else:
            job["state"]="Rejected"
            self.verdict(job,r.status_code in (409,422,503),f"KM refused the job with {r.status_code}")
        return self.public(job)
    def create_deletion(self,spec):
        res=spec.get("resource")
        if not res:
            fid=spec["documentFileId"]
            res={"sourceType":"DocumentLibraryFile","documentFileId":fid,"documentId":None,"version":None,"sourceEntityId":None,"applicationId":None,"recordId":None}
        if spec.get("deletionRequestId") in self.dels:return self.send_deletion(spec["deletionRequestId"]) # a resend, not a new request
        d={"deletionRequestId":spec.get("deletionRequestId") or str(uuid.uuid4()),"resource":res,"kmDeletionJobId":None,"state":"New",
           "callbacks":[],"verdicts":[],"timeline":[]}
        with self.lock:
            self.dels[d["deletionRequestId"]]=d
            for j in self.jobs.values():
                if j["documentFileId"]==res.get("documentFileId"):j["deleted"]=True # CSIT stops serving the file once it deletes it
        return self.send_deletion(d["deletionRequestId"])
    def send_deletion(self,rid):
        d=self.dels[rid]
        body={"schemaVersion":"1.0","sourceSystem":"CSIT","eventType":"DocumentDeletionRequested","deletionRequestId":rid,
              "requestedAt":now(),"reasonCode":"DocumentFileDeleted","resource":d["resource"]}
        self.ev(d,"POST /document-deletions")
        try:r=httpx.post(self.km+"/api/integrations/csit/v1/document-deletions",json=body,headers=self._headers(rid,False),timeout=self.timeout)
        except httpx.HTTPError as e:
            self.verdict(d,False,"KM unreachable: "+type(e).__name__);return self.public(d)
        self.ev(d,f"KM answered {r.status_code}",r.text[:300])
        if r.status_code==202:
            x=r.json()
            self.verdict(d,x.get("deletionRequestId")==rid and x.get("status")=="Accepted" and bool(x.get("kmDeletionJobId")),"202 body is {deletionRequestId,kmDeletionJobId,status:Accepted}")
            d["kmDeletionJobId"]=x.get("kmDeletionJobId");d["state"]="Accepted"
        else:
            d["state"]="Rejected";self.verdict(d,False,f"KM refused the deletion with {r.status_code}")
        return self.public(d)

    # ---------- KM -> CSIT ----------
    def serve_file(self,request,file_id):
        if not self._auth_ok(request):
            raise HTTPException(401,"service bearer required")
        with self.lock:
            job=next((j for j in self.jobs.values() if j["documentFileId"]==file_id),None)
            if job is None or job["deleted"]:
                if job:self.ev(job,"download refused: file deleted",404)
                raise HTTPException(404,"file not found")
            job["downloads"].append(now());n=len(job["downloads"]);f=job["faults"]
            if f["download"]=="unavailable" and n<=f["downloadFailures"]:
                self.ev(job,"download -> 503 (injected)",n);raise HTTPException(503,"temporarily unavailable")
            if f["download"]=="forbidden":self.ev(job,"download -> 403 (injected)");raise HTTPException(403,"forbidden")
            if f["download"]=="notfound":self.ev(job,"download -> 404 (injected)");raise HTTPException(404,"not found")
            data=job["content"]
            if f["download"]=="tamper":data=data[:-1]+bytes([data[-1]^1]);self.ev(job,"download served with altered bytes (injected)")
            elif f["download"]=="truncate":data=data[:len(data)//2];self.ev(job,"download truncated (injected)")
            else:self.ev(job,"download served",{"attempt":n,"bytes":len(data)})
            if job["state"]=="Accepted":job["state"]="Downloading"
        return Response(data,media_type="application/octet-stream")
    def _find(self,table,key,value):
        return next((x for x in table.values() if x.get(key)==value),None)
    def receive(self,request,payload,kind):
        if not self._auth_ok(request):raise HTTPException(401,"service bearer required")
        with self.lock:
            g=self.global_faults
            if g["callbackFailures"]>0:
                g["callbackFailures"]-=1
                raise HTTPException(g["callbackStatus"],"injected failure")
            if kind=="ingestion":
                problems=check_ingestion_callback(payload);obj=self._find(self.jobs,"csitJobId",(payload or {}).get("csitJobId")) if isinstance(payload,dict) else None
                label="ingestion"
            else:
                problems=check_deletion_callback(payload);obj=self._find(self.dels,"deletionRequestId",(payload or {}).get("deletionRequestId")) if isinstance(payload,dict) else None
                label="deletion"
            if obj is None:
                self.violations.append({"ref":None,"what":f"{label} callback for an unknown job"})
                raise HTTPException(404,"unknown job")
            status=payload.get("status") if isinstance(payload,dict) else None
            self.ev(obj,f"callback {status}",{"callbackId":(payload or {}).get("callbackId")})
            if problems:
                for pr in problems:self.verdict(obj,False,f"{status} callback: {pr}")
                raise HTTPException(400,{"problems":problems})
            self.verdict(obj,True,f"{status} callback matches the spec")
            km_key="kmJobId" if kind=="ingestion" else "kmDeletionJobId"
            if obj.get(km_key) and payload.get(km_key)!=obj[km_key]:
                self.verdict(obj,False,f"{km_key} differs from the one returned in the 202");raise HTTPException(409,"correlation mismatch")
            if kind=="ingestion" and payload["documentFileId"]!=obj["documentFileId"]:
                self.verdict(obj,False,"documentFileId does not belong to this csitJobId");raise HTTPException(409,"correlation mismatch")
            cid=payload["callbackId"];canon=json.dumps(payload,sort_keys=True)
            if cid in self.seen_callbacks:
                if self.seen_callbacks[cid]==canon:
                    self.ev(obj,"duplicate callbackId, same body -> 204");return Response(status_code=204)
                self.verdict(obj,False,"same callbackId reused with a different body");raise HTTPException(409,"callbackId conflict")
            if obj["state"] in ("Completed","Failed") and status!=obj["state"]:
                self.verdict(obj,False,f"{status} callback arrived after terminal {obj['state']} (must not overwrite)")
                raise HTTPException(409,"late status after terminal")
            if obj["state"]=="Processing" and status=="Processing":
                self.verdict(obj,False,"second Processing callback (status must not regress)")
            self.seen_callbacks[cid]=canon;obj["callbacks"].append(payload)
            if status=="Completed" and kind=="deletion":self.verdict(obj,True,"cleanupVerified=true with seven verified items")
            obj["state"]=status
            return Response(status_code=204)

    # ---------- reporting ----------
    def public(self,o):
        view={k:v for k,v in o.items() if k not in ("content","callbacks")}
        view["callbackStatuses"]=[c.get("status") for c in o["callbacks"]]
        view["result"]=next((c.get("result") for c in o["callbacks"] if c.get("status")=="Completed"),None)
        view["sizeBytes"]=len(o["content"]) if "content" in o else None
        return view
    def state(self):
        with self.lock:
            return {"jobs":[self.public(j) for j in self.jobs.values()],"deletions":[self.public(d) for d in self.dels.values()],
                    "violations":list(self.violations),"faults":self.global_faults}
    def report(self):
        s=self.state();allv=[v for x in s["jobs"]+s["deletions"] for v in x["verdicts"]]
        return {"passed":sum(1 for v in allv if v["ok"]),"failed":sum(1 for v in allv if not v["ok"]),"violations":s["violations"],
                "jobs":len(s["jobs"]),"deletions":len(s["deletions"])}

def create_app(sim:Sim):
    app=FastAPI(title="CSIT simulator",docs_url="/docs")
    @app.get(BASE+"/document-library/files/{file_id}/content")
    def content(file_id:str,request:Request):return sim.serve_file(request,file_id)
    @app.post(BASE+"/document-library/ingestion-status")
    async def ingestion(request:Request):return sim.receive(request,await _json(request),"ingestion")
    @app.post(BASE+"/document-deletion-status")
    async def deletion(request:Request):return sim.receive(request,await _json(request),"deletion")
    async def _json(request):
        try:return await request.json()
        except ValueError:raise HTTPException(400,"body is not JSON") from None
    # control API used by the UI and the drill
    @app.post("/sim/jobs")
    async def new_job(request:Request):return sim.create_job(await request.json())
    @app.post("/sim/jobs/{csit_job_id}/resend")
    def resend(csit_job_id:str):
        if csit_job_id not in sim.jobs:raise HTTPException(404)
        return sim.send_job(csit_job_id)
    @app.post("/sim/deletions")
    async def new_deletion(request:Request):return sim.create_deletion(await request.json())
    @app.post("/sim/faults")
    async def faults(request:Request):
        d=await request.json()
        with sim.lock:sim.global_faults.update({k:int(d[k]) for k in ("callbackFailures","callbackStatus") if k in d})
        return sim.global_faults
    @app.get("/sim/state")
    def state():return sim.state()
    @app.get("/sim/report")
    def report():return sim.report()
    @app.post("/sim/reset")
    def reset():sim.reset();return {"ok":True}
    @app.get("/",response_class=HTMLResponse)
    def ui():return (Path(__file__).parent/"ui.html").read_text(encoding="utf-8")
    return app
