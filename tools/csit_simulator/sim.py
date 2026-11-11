"""CSIT simulator engine: a document library that behaves like CSIT toward KM (spec v1.3).

A document moves 上傳 -> 核准 -> NAS 歸檔 -> 派送 KM -> KM 處理 exactly as spec section 4.1 describes, one manual step at a time or
all at once. Every HTTP exchange with KM is recorded (traffic) and every KM behaviour is judged against the spec (verdicts).
"""
import base64,hashlib,json,threading,time,uuid
from datetime import datetime,timezone
from pathlib import Path
import httpx
from fastapi import HTTPException,Request,Response
from .checks import check_ingestion_callback,check_deletion_callback
from .v2 import V2Mixin,READ_SCOPES,file_route

BASE="/api/integrations/km/v1"
# L1 = the zones in the KM left navigation, with the names it shows. L2/L3 are examples (the real CSIT list is not known to the simulator).
TAXONOMY=[
 {"id":"20","name":"WiFi 知識專區","children":[{"id":"21","name":"規格文件","children":[]},{"id":"22","name":"測試報告","children":[{"id":"221","name":"Wi-Fi 7"}]}]},
 {"id":"40","name":"行動通訊知識專區","children":[{"id":"41","name":"LTE / 5G NR","children":[]},{"id":"42","name":"Small Cell","children":[]}]},
 {"id":"50","name":"固網寬頻知識專區","children":[{"id":"51","name":"PON","children":[]},{"id":"52","name":"Cable","children":[]}]},
 {"id":"30","name":"認證知識專區","children":[{"id":"31","name":"NCC","children":[]},{"id":"32","name":"CE","children":[]}]},
 {"id":"60","name":"產品驗證專區","children":[{"id":"61","name":"測試報告","children":[]},{"id":"62","name":"產品資訊","children":[]},{"id":"63","name":"申請單文件","children":[]}]},
 {"id":"10","name":"設備儀器專區","children":[{"id":"11","name":"頻譜分析儀","children":[{"id":"111","name":"FSW 系列"},{"id":"112","name":"MS269x 系列"}]},
                                    {"id":"12","name":"網路分析儀","children":[]}]},
 {"id":"70","name":"實驗室管理專區","children":[]},
 {"id":"80","name":"Confluence / Jira / TestRail 查詢專區","children":[]},
 {"id":"90","name":"部門與公司文管專區","children":[]}]
# CSIT does not classify documents into KM zones. KM reads the content with its LLM: a Test Report goes to 產品驗證專區 whatever its technology, any other
# document to the zone its content belongs to. The classification a CSIT user picks (L1/L2/L3 above) travels in the notice but is only a fallback for KM.
VERIFICATION_ZONE="產品驗證專區"
def expected_zone(source_type,l1_name=None):
    """What can be said before KM has looked at the content: a Test Report source is 產品驗證專區; anything else is decided by KM's LLM (None here)."""
    return VERIFICATION_ZONE if source_type=="TestReport" else None
NEXT={"PendingApproval":"approve","Approved":"archive","Archived":"dispatch"}

def now():return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
def _find_class(node_id,nodes):
    for n in nodes:
        if n["id"]==node_id:return {"id":n["id"],"name":n["name"]}
        r=_find_class(node_id,n.get("children",[]))
        if r:return r
    return None

FAMILY={"library":("DocumentLibraryFile",),"documents":("VerificationApplicationAttachment","TestReport"),"vendor":("VendorFile",),"equipment":("EquipmentAttachment",)}

class Sim(V2Mixin):
    def __init__(self,km_base_url,token,timeout=15,data_dir=None,inspect=None,identity=None,public_base="",scope_style="v13"):
        self.km=km_base_url.rstrip("/");self.token=token;self.timeout=timeout
        self.public_base=public_base.rstrip("/") # the address KM reaches this simulator at; shown in downloadUrl (KM fetches by id from its configured CSIT address)
        self.scope_style=scope_style # v13: km.ingestion.submit everywhere; v14: the endpoint-specific names of spec 3.2
        self.identity=identity # tools.csit_simulator.identity.Identity: signed tokens instead of the shared DEV bearer
        self.inspect=inspect # callable -> dict (only the local demo can look inside KM)
        self.dir=Path(data_dir) if data_dir else None
        self.lock=threading.RLock()
        self.reset(clear_disk=False)
        if self.dir:self._load()

    # ---------- state ----------
    def reset(self,clear_disk=True):
        with self.lock:
            self.docs={};self.jobs={};self.dels={};self.changes={};self.analyses=[];self.seen={};self.traffic=[];self.tid=0;self.violations=[]
            self.faults={"callbackFailures":0,"callbackStatus":503,"resolver":"ok"}
            if clear_disk and self.dir and (self.dir/"content").is_dir():
                for f in (self.dir/"content").glob("*"):f.unlink()
                (self.dir/"state.json").unlink(missing_ok=True)
    def _save(self):
        if not self.dir:return
        with self.lock:
            self.dir.mkdir(parents=True,exist_ok=True);(self.dir/"content").mkdir(exist_ok=True)
            for d in self.docs.values():
                if d["content"] is not None:(self.dir/"content"/(d["id"]+".bin")).write_bytes(d["content"])
            snap={"docs":{k:{x:y for x,y in v.items() if x!="content"} for k,v in self.docs.items()},"jobs":self.jobs,"dels":self.dels,"changes":self.changes,"analyses":self.analyses[-50:],
                  "seen":self.seen,"traffic":self.traffic[-300:],"tid":self.tid,"violations":self.violations}
            tmp=self.dir/"state.tmp";tmp.write_text(json.dumps(snap,ensure_ascii=False),encoding="utf-8");tmp.replace(self.dir/"state.json")
    def _load(self):
        f=self.dir/"state.json"
        if not f.is_file():return
        s=json.loads(f.read_text(encoding="utf-8"))
        self.docs=s["docs"];self.jobs=s["jobs"];self.dels=s["dels"];self.changes=s.get("changes",{});self.analyses=s.get("analyses",[]);self.seen=s["seen"];self.traffic=s["traffic"];self.tid=s["tid"];self.violations=s["violations"]
        for k,d in self.docs.items():
            p=self.dir/"content"/(k+".bin");d["content"]=p.read_bytes() if p.is_file() else None
            d.setdefault("sourceType","DocumentLibraryFile");d.setdefault("version",1);d.setdefault("changeIds",[]);d.setdefault("entityId",d["id"])

    # ---------- bookkeeping ----------
    def ev(self,obj,kind,detail=None):obj["timeline"].append({"t":now(),"kind":kind,"detail":detail})
    def verdict(self,obj,ok,what,ref=None):
        obj["verdicts"].append({"ok":ok,"what":what,"t":now()})
        if not ok:self.violations.append({"ref":ref or obj.get("name") or obj.get("id"),"what":what})
    def log(self,direction,method,path,status,req=None,resp=None,doc=None,ms=None,note=None):
        with self.lock:
            self.tid+=1
            self.traffic.append({"id":self.tid,"t":now(),"direction":direction,"method":method,"path":path,"status":status,"ms":ms,
                                 "request":req,"response":resp,"docId":doc,"note":note})
            del self.traffic[:-500]
    def _now(self):return now()
    def _headers(self,key,bad=False,endpoint=None):
        scope=None
        if self.scope_style=="v14" and endpoint:
            from .identity import INBOUND_SCOPES_V14
            scope=INBOUND_SCOPES_V14[endpoint]
        token="not-the-real-token" if bad else (self.identity.mint_for_km(scope) if self.identity else self.token)
        h={"Authorization":"Bearer "+token,"Content-Type":"application/json"}
        if key:h["Idempotency-Key"]=key
        return h
    def _auth_ok(self,request,scope=None):
        header=request.headers.get("authorization","")
        return self.identity.verify_from_km(header,scope) if self.identity else header=="Bearer "+self.token

    # ---------- documents (CSIT's own workflow) ----------
    def create_doc(self,spec):
        content=base64.b64decode(spec["contentBase64"]) if spec.get("contentBase64") else spec.get("contentText","").encode()
        cls={}
        for lvl in ("l1","l2","l3"):
            cid=(spec.get("classification") or {}).get(lvl)
            cls[lvl]=_find_class(cid,TAXONOMY) if cid else None
        d={"id":spec.get("documentFileId") or str(uuid.uuid4()),"name":spec.get("fileName","document.txt"),"size":len(content),
           "sha256":hashlib.sha256(content).hexdigest(),"contentType":spec.get("contentType","text/plain"),"classification":cls,
           "uploader":spec.get("uploader","simulator.user"),"stage":"PendingApproval","archived":False,"approvedBy":None,
           "faults":{"download":"none","downloadFailures":2,"badToken":False,"noIdempotencyKey":False,"wrongDeclaredSha":False},
           "jobIds":[],"delIds":[],"timeline":[],"verdicts":[],"content":content,"uploadedAt":now(),"kmStatus":None,"deleteState":None}
        self._v2_fields(spec,d)
        if "downloadFault" in spec:d["faults"]["download"]=spec["downloadFault"]
        if "downloadFailures" in spec:d["faults"]["downloadFailures"]=int(spec["downloadFailures"])
        for k in ("badToken","noIdempotencyKey","wrongDeclaredSha"):
            if k in spec:d["faults"][k]=bool(spec[k])
        with self.lock:self.docs[d["id"]]=d
        self.ev(d,"員工上傳","進入待核准(Approval Staging)")
        if spec.get("autoRun"):self.run_all(d["id"])
        self._save();return self.view(d)
    def _doc(self,doc_id):
        d=self.docs.get(doc_id)
        if d is None:raise HTTPException(404,"unknown document")
        return d
    def approve(self,doc_id,by="manager.sim"):
        d=self._doc(doc_id)
        if d["stage"]!="PendingApproval":raise HTTPException(409,"only a pending document can be approved")
        d["stage"]="Approved";d["approvedBy"]=by
        d["approval"]={"mode":d.get("approvalMode","Approved"),"referenceId":str(uuid.uuid4()),"approvedAt":now()};self.ev(d,"主管核准",by);self._save();return self.view(d)
    def reject(self,doc_id):
        d=self._doc(doc_id)
        if d["stage"]!="PendingApproval":raise HTTPException(409,"only a pending document can be rejected")
        d["stage"]="Rejected";self.ev(d,"主管退回","不會歸檔,不會通知 KM");self._save();return self.view(d)
    def archive(self,doc_id):
        d=self._doc(doc_id)
        if d["stage"]!="Approved":raise HTTPException(409,"approve first: KM is notified only after the NAS archive")
        d["stage"]="Archived";d["archived"]=True;d["archivedAt"]=now();self.ev(d,"CSIT NAS 正式入庫","ArchiveStatus=Completed,建立 KM Outbox");self._save();return self.view(d)
    def run_all(self,doc_id):
        d=self._doc(doc_id)
        if d["stage"]=="PendingApproval":self.approve(doc_id)
        if d["stage"]=="Approved":self.archive(doc_id)
        if d["stage"]=="Archived":return self.dispatch(doc_id)
        return self.view(d)
    def advance(self,doc_id):
        d=self._doc(doc_id);step=NEXT.get(d["stage"])
        if not step:raise HTTPException(409,"nothing to advance from "+d["stage"])
        return getattr(self,step)(doc_id)
    def dispatch(self,doc_id,new_job=False):
        """Outbox -> KM. Without new_job a resend reuses the same csitJobId (idempotency); with it, a second job is created."""
        d=self._doc(doc_id)
        if not d["archived"]:raise HTTPException(409,"NAS archive must complete before KM is notified")
        if d["stage"]=="Rejected":raise HTTPException(409,"document was rejected")
        mode=self.km_mode()
        if mode:d["kmModes"]=sorted(set(d.get("kmModes",[]))|{mode}) # which KM data this document went into; the "live" ones can be purged
        # A Purged document may still be dispatched on purpose: KM must refuse it (tombstone), which is exactly what we want to observe.
        if self.route(d)=="v2":return self._dispatch_v2(d,new_job)
        if self.route(d)=="report1":return self._dispatch_report_v1(d)
        with self.lock:
            if d["jobIds"] and not new_job:cid=d["jobIds"][-1]
            else:
                cid=str(uuid.uuid4())
                self.jobs[cid]={"csitJobId":cid,"docId":d["id"],"kmJobId":None,"state":"New","callbacks":[],"downloads":[],"verdicts":[],
                                "timeline":[],"sendCount":0}
                d["jobIds"].append(cid)
        if d["stage"]=="Archived":d["stage"]="Dispatched"
        self._send_job(d,self.jobs[cid]);self._save();return self.view(d)
    def _send_job(self,d,job):
        f=d["faults"]
        sha="0"*64 if f["wrongDeclaredSha"] else d["sha256"]
        body={"schemaVersion":"1.0","sourceSystem":"CSIT","eventType":"DocumentLibraryFileUploaded","documentFileId":d["id"],
              "csitJobId":job["csitJobId"],"occurredAt":now(),
              "file":{"originalFileName":d["name"],"standardFileName":d["name"],"contentType":d["contentType"],"fileSizeBytes":d["size"],
                      "sha256":sha,"downloadUrl":f"{self.km}{BASE}/document-library/files/{d['id']}/content"},
              "classification":d["classification"]}
        job["sendCount"]+=1
        path="/api/integrations/csit/v1/document-library/jobs"
        self.ev(job,"CSIT→KM 派送通知",f"第 {job['sendCount']} 次")
        t0=time.monotonic()
        try:r=httpx.post(self.km+path,json=body,headers=self._headers(None if f["noIdempotencyKey"] else job["csitJobId"],f["badToken"]),timeout=self.timeout)
        except httpx.HTTPError as e:
            self.log("CSIT→KM","POST",path,None,body,{"error":type(e).__name__},d["id"],note="KM 無法連線")
            self.ev(job,"KM 無法連線",type(e).__name__);self.verdict(job,False,"KM unreachable: "+type(e).__name__,d["name"]);self.ev(d,"派送失敗","KM 無法連線");return
        ms=int((time.monotonic()-t0)*1000)
        try:resp=r.json()
        except ValueError:resp=r.text[:400]
        self.log("CSIT→KM","POST",path,r.status_code,body,resp,d["id"],ms)
        self.ev(job,f"KM 回應 {r.status_code}",resp if r.status_code!=202 else None)
        if f["badToken"]:
            self.verdict(job,r.status_code==401,f"invalid bearer token is rejected with 401 (got {r.status_code})",d["name"])
        elif r.status_code==202:
            ok=isinstance(resp,dict) and resp.get("csitJobId")==job["csitJobId"] and resp.get("status")=="Accepted" and bool(resp.get("kmJobId"))
            self.verdict(job,ok,"202 body is {csitJobId,kmJobId,status:Accepted}",d["name"])
            if job["kmJobId"]:
                same=isinstance(resp,dict) and resp.get("kmJobId")==job["kmJobId"]
                self.verdict(job,same,"resend returned the original kmJobId (idempotent)" if same else "resend returned a different kmJobId (must be idempotent)",d["name"])
            if isinstance(resp,dict):job["kmJobId"]=resp.get("kmJobId");d["kmJobId"]=resp.get("kmJobId")
            if job["state"]=="New":job["state"]="Accepted"
            if d["kmStatus"] is None:d["kmStatus"]="Accepted"
            self.ev(d,"KM 已受理(202)",job["kmJobId"])
        else:
            job["state"]="Rejected";d["kmStatus"]="Rejected"
            self.verdict(job,r.status_code in (409,422,503),f"KM refused the job with {r.status_code}",d["name"]);self.ev(d,f"KM 拒絕通知({r.status_code})")
    def set_faults(self,doc_id,faults):
        d=self._doc(doc_id)
        for k in ("download","downloadFailures","badToken","noIdempotencyKey","wrongDeclaredSha"):
            if k in faults:d["faults"][k]=int(faults[k]) if k=="downloadFailures" else (faults[k] if k=="download" else bool(faults[k]))
        self._save();return self.view(d)
    def delete(self,doc_id,deletion_request_id=None):
        d=self._doc(doc_id)
        if not d["archived"]:raise HTTPException(409,"nothing was archived, so KM has nothing to delete")
        if self.route(d)=="v2":return self._delete_v2(d,deletion_request_id)
        if self.route(d)=="report1":return self._delete_report_v1(d,deletion_request_id)
        rid=deletion_request_id or str(uuid.uuid4())
        if rid in self.dels:return self._send_deletion(self.dels[rid])
        res={"sourceType":"DocumentLibraryFile","documentFileId":d["id"],"documentId":None,"version":None,"sourceEntityId":None,"applicationId":None,"recordId":None}
        x={"deletionRequestId":rid,"docId":d["id"],"resource":res,"kmDeletionJobId":None,"state":"New","callbacks":[],"verdicts":[],"timeline":[]}
        with self.lock:self.dels[rid]=x;d["delIds"].append(rid)
        d["stage"]="Deleting";d["deleteState"]="Requested";self.ev(d,"使用者刪除文件","通知 KM;KM 驗證清理完成後,CSIT 才刪自己的檔案")
        return self._send_deletion(x)
    def _send_deletion(self,x):
        d=self.docs[x["docId"]]
        body={"schemaVersion":"1.0","sourceSystem":"CSIT","eventType":"DocumentDeletionRequested","deletionRequestId":x["deletionRequestId"],
              "requestedAt":now(),"reasonCode":x.get("reason","DocumentFileDeleted"),"resource":x["resource"]}
        path="/api/integrations/csit/v1/document-deletions";self.ev(x,"CSIT→KM 刪除通知")
        t0=time.monotonic()
        try:r=httpx.post(self.km+path,json=body,headers=self._headers(x["deletionRequestId"]),timeout=self.timeout)
        except httpx.HTTPError as e:
            self.log("CSIT→KM","POST",path,None,body,{"error":type(e).__name__},d["id"],note="KM 無法連線")
            self.verdict(x,False,"KM unreachable: "+type(e).__name__,d["name"]);self._save();return self.view(d)
        ms=int((time.monotonic()-t0)*1000)
        try:resp=r.json()
        except ValueError:resp=r.text[:400]
        self.log("CSIT→KM","POST",path,r.status_code,body,resp,d["id"],ms);self.ev(x,f"KM 回應 {r.status_code}")
        if r.status_code==202:
            ok=isinstance(resp,dict) and resp.get("deletionRequestId")==x["deletionRequestId"] and resp.get("status")=="Accepted" and bool(resp.get("kmDeletionJobId"))
            self.verdict(x,ok,"202 body is {deletionRequestId,kmDeletionJobId,status:Accepted}",d["name"])
            if isinstance(resp,dict):x["kmDeletionJobId"]=resp.get("kmDeletionJobId")
            x["state"]="Accepted";d["deleteState"]="Accepted";self.ev(d,"KM 已受理刪除(202)",x["kmDeletionJobId"])
        else:
            x["state"]="Rejected";self.verdict(x,False,f"KM refused the deletion with {r.status_code}",d["name"])
        self._save();return self.view(d)

    # ---------- KM -> CSIT ----------
    def serve_file(self,request,file_id,family="library",version=None):
        t0=time.monotonic()
        path={"library":f"{BASE}/document-library/files/{file_id}/content","documents":f"{BASE}/documents/{file_id}/versions/{version}/content",
              "vendor":f"{BASE}/vendor-files/{file_id}/content","equipment":f"{BASE}/equipment-documents/{file_id}/content"}[family]
        def refuse(code,note,doc=None):
            self.log("KM→CSIT","GET",path,code,None,{"detail":note},doc,int((time.monotonic()-t0)*1000),note)
            raise HTTPException(code,note)
        if not self._auth_ok(request,READ_SCOPES):refuse(401,"service bearer required")
        with self.lock:
            d=self.docs.get(file_id)
            if d is not None and (d["sourceType"] not in FAMILY[family] or (version is not None and d["version"]!=version)):d=None
            if d is None or d["content"] is None or not d["archived"]:refuse(404,"file not found (not archived, deleted, or unknown)",file_id if d else None)
            job=self.jobs.get(d["jobIds"][-1]) if d["jobIds"] else None
            if job is not None:job["downloads"].append(now())
            n=len(job["downloads"]) if job else 1;f=d["faults"]
            if f["download"]=="unavailable" and n<=f["downloadFailures"]:
                self.ev(d,f"KM 下載 → 503(注入,第 {n} 次)");refuse(503,"temporarily unavailable (injected)",d["id"])
            if f["download"]=="forbidden":self.ev(d,"KM 下載 → 403(注入)");refuse(403,"forbidden (injected)",d["id"])
            if f["download"]=="notfound":self.ev(d,"KM 下載 → 404(注入)");refuse(404,"not found (injected)",d["id"])
            data=d["content"];note="served"
            if f["download"]=="tamper":data=data[:-1]+bytes([data[-1]^1]);note="served with ALTERED bytes (injected)"
            elif f["download"]=="truncate":data=data[:len(data)//2];note="served TRUNCATED (injected)"
            self.ev(d,"KM 下載檔案",f"{len(data)} bytes · {note}")
            if job and job["state"]=="Accepted":job["state"]="Downloading"
            if d["kmStatus"]=="Accepted":d["kmStatus"]="Downloading"
        self.log("KM→CSIT","GET",path,200,None,{"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"note":note},d["id"],int((time.monotonic()-t0)*1000))
        self._save()
        if family=="documents":
            # The v1 Test Report download checks the Content-Type and the filename against the notice; the v2 clients ignore both.
            from urllib.parse import quote
            name=d["name"];cd=f'attachment; filename="{name}"' if name.isascii() else f"attachment; filename*=UTF-8''{quote(name)}"
            return Response(data,media_type=d["contentType"],headers={"Content-Disposition":cd})
        return Response(data,media_type="application/octet-stream")
    def receive(self,request,payload,kind):
        t0=time.monotonic()
        path=f"{BASE}/document-library/ingestion-status" if kind=="ingestion" else f"{BASE}/document-deletion-status"
        def answer(code,note=None,doc=None,raise_=False):
            self.log("KM→CSIT","POST",path,code,payload,{"note":note} if note else None,doc,int((time.monotonic()-t0)*1000))
            self._save()
            if raise_:raise HTTPException(code,note or "rejected")
            return Response(status_code=204)
        # CSIT Runtime 8fe25c60: the v1 deletion callback needs csit.km.deletion-status.write; the v1 ingestion callback keeps csit.ingestion.status.write.
        if not self._auth_ok(request,"csit.ingestion.status.write" if kind=="ingestion" else "csit.km.deletion-status.write"):return answer(401,"service bearer required",raise_=True)
        with self.lock:
            g=self.faults
            if g["callbackFailures"]>0:
                g["callbackFailures"]-=1;return answer(g["callbackStatus"],"injected CSIT failure",raise_=True)
            if kind=="ingestion":
                problems=check_ingestion_callback(payload);obj=self.jobs.get((payload or {}).get("csitJobId")) if isinstance(payload,dict) else None
            else:
                problems=check_deletion_callback(payload);obj=self.dels.get((payload or {}).get("deletionRequestId")) if isinstance(payload,dict) else None
            if obj is None:
                self.violations.append({"ref":None,"what":f"{kind} callback for an unknown job"});return answer(404,"unknown job",raise_=True)
            d=self.docs[obj["docId"]];status=payload.get("status")
            self.ev(obj,f"KM→CSIT 回報 {status}",{"callbackId":payload.get("callbackId")})
            if problems:
                for pr in problems:self.verdict(obj,False,f"{status} callback: {pr}",d["name"])
                return answer(400,"; ".join(problems)[:300],d["id"],True)
            self.verdict(obj,True,f"{status} callback matches the spec",d["name"])
            kmkey="kmJobId" if kind=="ingestion" else "kmDeletionJobId"
            if obj.get(kmkey) and payload.get(kmkey)!=obj[kmkey]:
                self.verdict(obj,False,f"{kmkey} differs from the one returned in the 202",d["name"]);return answer(409,"correlation mismatch",d["id"],True)
            if kind=="ingestion" and payload["documentFileId"]!=obj["docId"]:
                self.verdict(obj,False,"documentFileId does not belong to this csitJobId",d["name"]);return answer(409,"correlation mismatch",d["id"],True)
            cid=payload["callbackId"];canon=json.dumps(payload,sort_keys=True)
            if cid in self.seen:
                if self.seen[cid]==canon:
                    self.ev(obj,"重複的 callbackId(內容相同)→ 204");return answer(204,"duplicate, idempotent",d["id"])
                self.verdict(obj,False,"same callbackId reused with a different body",d["name"]);return answer(409,"callbackId conflict",d["id"],True)
            if obj["state"] in ("Completed","Failed") and status!=obj["state"]:
                self.verdict(obj,False,f"{status} callback arrived after terminal {obj['state']} (must not overwrite)",d["name"])
                return answer(409,"late status after terminal",d["id"],True)
            if obj["state"]=="Processing" and status=="Processing":self.verdict(obj,False,"second Processing callback (status must not regress)",d["name"])
            self.seen[cid]=canon;obj["callbacks"].append(payload);obj["state"]=status
            if kind=="ingestion":
                d["kmStatus"]=status
                if status=="Completed":d["result"]=payload["result"];self.ev(d,"KM 完成:取得 AI Metadata","索引已持久化")
                elif status=="Failed":d["error"]=payload["error"];self.ev(d,"KM 失敗",payload["error"])
                else:self.ev(d,"KM 開始處理(Processing)")
            else:
                if status=="Completed":
                    self.verdict(obj,True,"cleanupVerified=true with seven verified items",d["name"])
                    d["stage"]="Purged";d["deleteState"]="Verified";d["content"]=None
                    self.ev(d,"KM 驗證清理完成 → CSIT 才刪自己的檔案","CSIT NAS 檔案已移除")
                    if self.dir:(self.dir/"content"/(d["id"]+".bin")).unlink(missing_ok=True)
                elif status=="Failed":d["deleteState"]="Failed";self.ev(d,"KM 刪除失敗",payload["error"])
                else:d["deleteState"]="Processing";self.ev(d,"KM 開始清理(Processing)")
            return answer(204,None,d["id"])

    # ---------- views ----------
    def _dview(self,x):
        v={k:val for k,val in x.items() if k!="callbacks"}
        v["callbackStatuses"]=[c.get("status") for c in x["callbacks"]]
        v["result"]=next((c.get("result") for c in x["callbacks"] if c.get("status")=="Completed"),None)
        v["error"]=next((c.get("error") for c in x["callbacks"] if c.get("status")=="Failed"),None)
        return v
    def view(self,d):
        v={k:val for k,val in d.items() if k!="content"}
        v["hasContent"]=d["content"] is not None
        v["jobs"]=[self._dview(self.jobs[c]) for c in d["jobIds"]]
        v["dels"]=[self._dview(self.dels[c]) for c in d["delIds"]]
        v["changes"]=[self._dview(self.changes[c]) for c in d.get("changeIds",[])]
        v["downloadPath"]=file_route(d)
        v["expectedZone"]=expected_zone(d.get("sourceType","DocumentLibraryFile"))
        v["allVerdicts"]=d["verdicts"]+[x for j in v["jobs"] for x in j["verdicts"]]+[x for j in v["dels"] for x in j["verdicts"]]+[x for j in v["changes"] for x in j["verdicts"]]
        return v
    def state(self):
        with self.lock:
            return {"docs":[self.view(d) for d in self.docs.values()],"violations":list(self.violations),"faults":dict(self.faults),
                    "settings":{"kmBaseUrl":self.km,"hasToken":bool(self.token) or bool(self.identity),"identity":bool(self.identity),"inspectAvailable":self.inspect is not None}}
    def report(self):
        with self.lock:
            vs=[v for d in self.docs.values() for v in self.view(d)["allVerdicts"]]
            return {"passed":sum(1 for v in vs if v["ok"]),"failed":sum(1 for v in vs if not v["ok"]),"violations":list(self.violations),"docs":len(self.docs)}
    def traffic_since(self,after=0):
        with self.lock:return [t for t in self.traffic if t["id"]>after]
    def ping(self):
        try:
            r=httpx.get(self.km+"/health",timeout=5);return {"ok":r.status_code==200,"status":r.status_code,"body":r.text[:200]}
        except httpx.HTTPError as e:return {"ok":False,"error":type(e).__name__}
    def configure(self,km_base_url=None,token=None):
        if km_base_url:self.km=km_base_url.rstrip("/")
        if token:self.token=token
