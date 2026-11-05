"""CSIT simulator, spec v1.4: v2 document notices, metadata changes, v2 deletion, and the v2 callbacks KM sends back.

Mixed into Sim. The v1.3 document-library flow in sim.py is untouched; a document whose sourceType is not DocumentLibraryFile
takes the paths below. The places KM fetches files from are the simulator's own routes (see app.py / FILE_ROUTES).
"""
import json,time,uuid
import httpx
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from .checks import (check_job_callback_v2,check_change_callback,check_deletion_callback_v2,check_analysis_result,check_report_callback_v1,SOURCE_TYPES_V2)

KM_V2="/api/integrations/csit/v2"
# v1.4.1 C.4: the closed event set. TestReportCommitted / DocumentLibraryFileUploaded on the v2 route only carry a replacement (supersedes).
EVENT_TYPE={"VerificationApplicationAttachment":"VerificationApplicationAttachmentArchived","VendorFile":"VendorFileArchived",
            "EquipmentAttachment":"EquipmentAttachmentArchived","TestReport":"TestReportCommitted","DocumentLibraryFile":"DocumentLibraryFileUploaded"}
MODULE={"VerificationApplicationAttachment":"verification-applications","VendorFile":"vendor-files","EquipmentAttachment":"equipment",
        "TestReport":"test-reports","DocumentLibraryFile":"document-library"}
REPORT_V1="/api/integrations/csit/v1/ingestion-jobs"
CORRELATION="/api/integrations/km/v2/test-report-correlations/"
# route family -> (source types served, scope aliases that allow the download)
# v1.4.1 C.3: csit.document.read (singular) for GET, csit.km.status.write for v2 job / change / analysis callbacks, csit.km.deletion-status.write
# for v2 deletion callbacks. The v1 callbacks keep csit.ingestion.status.write.
READ_SCOPES=("csit.document.read",)
STATUS_SCOPES=("csit.km.status.write",)
DELETION_SCOPES=("csit.km.deletion-status.write",)
V1_STATUS_SCOPES=("csit.ingestion.status.write",)
V2_PATHS={"jobs":"/api/integrations/km/v2/document-jobs/status","changes":"/api/integrations/km/v2/document-metadata-changes/status",
          "deletions":"/api/integrations/km/v2/document-deletions/status","analysis":"/api/integrations/km/v2/analysis-results"}

def file_route(d,public=""):
    """Where KM fetches this document from (spec section 2). Relative to the CSIT base URL."""
    t,i=d.get("sourceType","DocumentLibraryFile"),d["id"]
    if t in ("VerificationApplicationAttachment","TestReport"):return public+f"/api/integrations/km/v1/documents/{i}/versions/{d.get('version',1)}/content"
    if t=="VendorFile":return public+f"/api/integrations/km/v1/vendor-files/{i}/content"
    if t=="EquipmentAttachment":return public+f"/api/integrations/km/v1/equipment-documents/{i}/content"
    return public+f"/api/integrations/km/v1/document-library/files/{i}/content"

class V2Mixin:
    # ---------- how a document is delivered ----------
    @staticmethod
    def route(d):
        """v1 = the v1.3 document-library route; report1 = the existing Test Report v1 route; v2 = /v2/document-jobs.
        A Test Report or library file is only sent on v2 when it replaces an older version (spec v1.4.1 answer 5)."""
        st,sup=d.get("sourceType","DocumentLibraryFile"),d.get("supersedesDocId")
        if st=="DocumentLibraryFile" and not sup:return "v1"
        if st=="TestReport" and not sup:return "report1"
        return "v2"

    # ---------- Test Report v1 (unchanged by v1.4) ----------
    def _dispatch_report_v1(self,d):
        with self.lock:
            if d["jobIds"]:cid=d["jobIds"][-1]   # one outbox entry per source version: a resend reuses it
            else:
                cid=d["outboxId"]
                self.jobs[cid]={"csitJobId":cid,"eventId":d["eventId"],"v1report":True,"docId":d["id"],"kmJobId":None,"state":"New","callbacks":[],
                                "downloads":[],"verdicts":[],"timeline":[],"sendCount":0,"resolverCalls":0}
                d["jobIds"].append(cid)
        if d["stage"]=="Archived":d["stage"]="Dispatched"
        self._send_report_v1(d,self.jobs[cid]);self._save();return self.view(d)
    def _send_report_v1(self,d,job):
        f=d["faults"]
        body={"eventId":d["eventId"],"eventType":"TestReportCommitted","sourceSystem":"CSIT","documentId":d["id"],"version":d["version"],
              "project":d["project"],"case":d["case"],"task":d["task"],
              "document":{"fileName":d["name"],"contentType":d["contentType"],"sizeBytes":d["size"]},"committedAt":self._now()}
        job["sendCount"]+=1;self.ev(job,"CSIT→KM v1 測試報告通知",f"第 {job['sendCount']} 次")
        t0=time.monotonic()
        try:r=httpx.post(self.km+REPORT_V1,json=body,headers=self._headers(None if f["noIdempotencyKey"] else d["eventId"],f["badToken"]),timeout=self.timeout)
        except httpx.HTTPError as e:
            self.log("CSIT→KM","POST",REPORT_V1,None,body,{"error":type(e).__name__},d["id"],note="KM 無法連線")
            self.verdict(job,False,"KM unreachable: "+type(e).__name__,d["name"]);return
        try:resp=r.json()
        except ValueError:resp=r.text[:400]
        self.log("CSIT→KM","POST",REPORT_V1,r.status_code,body,resp,d["id"],int((time.monotonic()-t0)*1000))
        self.ev(job,f"KM 回應 {r.status_code}",resp if r.status_code!=202 else None)
        if f["badToken"]:
            self.verdict(job,r.status_code==401,f"invalid bearer token is rejected with 401 (got {r.status_code})",d["name"])
        elif r.status_code==202:
            ok=isinstance(resp,dict) and resp.get("documentId")==d["id"] and resp.get("version")==d["version"] and resp.get("sourceSystem")=="CSIT" \
               and resp.get("status") in ("Accepted","Processing","Completed","Failed") and bool(resp.get("jobId"))
            self.verdict(job,ok,"202 body is {jobId,sourceSystem,documentId,version,status}",d["name"])
            if job["kmJobId"] and isinstance(resp,dict):
                self.verdict(job,resp.get("jobId")==job["kmJobId"],"resend returned the original jobId (idempotent)",d["name"])
            if isinstance(resp,dict):job["kmJobId"]=resp.get("jobId");d["kmJobId"]=resp.get("jobId")
            if job["state"]=="New":job["state"]="Accepted"
            if d["kmStatus"] is None:d["kmStatus"]="Accepted"
            self.ev(d,"KM 已受理(202)",job["kmJobId"])
        else:
            job["state"]="Rejected";d["kmStatus"]="Rejected"
            self.verdict(job,r.status_code in (409,410,422,503),f"KM refused the job with {r.status_code}",d["name"]);self.ev(d,f"KM 拒絕通知({r.status_code})")

    def receive_report_v1(self,request,payload):
        """POST /km/v1/ingestion-status for a Test Report. No callbackId in v1: the same content again is idempotent."""
        t0=time.monotonic();path="/api/integrations/km/v1/ingestion-status"
        from fastapi import Response
        def answer(code,note=None,doc=None,raise_=False):
            self.log("KM→CSIT","POST",path,code,payload,{"note":note} if note else None,doc,int((time.monotonic()-t0)*1000));self._save()
            if raise_:raise HTTPException(code,note or "rejected")
            return Response(status_code=204)
        if not self._auth_ok(request,V1_STATUS_SCOPES):return answer(401,"service bearer required",raise_=True)
        with self.lock:
            g=self.faults
            if g["callbackFailures"]>0:
                g["callbackFailures"]-=1;return answer(g["callbackStatus"],"injected CSIT failure",raise_=True)
            problems=check_report_callback_v1(payload)
            job=next((j for j in self.jobs.values() if j.get("v1report") and isinstance(payload,dict) and j["docId"]==payload.get("documentId")
                      and self.docs[j["docId"]]["version"]==payload.get("version")),None)
            if job is None:
                self.violations.append({"ref":None,"what":"v1 Test Report callback for an unknown document / version"});return answer(404,"unknown job",raise_=True)
            d=self.docs[job["docId"]];status=payload.get("status");self.ev(job,f"KM→CSIT v1 回報 {status}")
            if problems:
                for pr in problems:self.verdict(job,False,f"{status} v1 callback: {pr}",d["name"])
                return answer(400,"; ".join(problems)[:300],d["id"],True)
            self.verdict(job,True,f"{status} v1 callback matches the spec",d["name"])
            if job["kmJobId"] and payload["jobId"]!=job["kmJobId"]:
                self.verdict(job,False,"jobId differs from the one returned in the 202",d["name"]);return answer(409,"correlation mismatch",d["id"],True)
            canon=json.dumps(payload,sort_keys=True)
            if canon in self.seen:self.ev(job,"重複的回報(內容相同)→ 204");return answer(204,"duplicate, idempotent",d["id"])
            if job["state"] in ("Completed","Failed") and status!=job["state"]:
                self.verdict(job,False,f"{status} callback arrived after terminal {job['state']} (must not overwrite)",d["name"])
                return answer(409,"late status after terminal",d["id"],True)
            self.seen[canon]=canon;job["callbacks"].append(payload);job["state"]=status;d["kmStatus"]=status
            if status=="Completed":self.ev(d,"KM 完成(v1 狀態,不含 Metadata)","完整分析結果之後由 v2 analysis-results 另送")
            elif status=="Failed":d["error"]=payload.get("error");self.ev(d,"KM 失敗",payload.get("error"))
            else:self.ev(d,"KM 開始處理(Processing)")
            return answer(204,None,d["id"])

    # ---------- Test Report Correlation Resolver (spec v1.4.1 C.2) ----------
    def resolve_report(self,request,event_id,document_id,version,km_job_id):
        t0=time.monotonic();path=CORRELATION+event_id
        q={"documentId":document_id,"version":version,"kmJobId":km_job_id}
        def reply(code,body,doc=None,note=None):
            self.log("KM→CSIT","GET",path+"?"+"&".join(f"{k}={v}" for k,v in q.items()),code,None,body if isinstance(body,dict) else {"detail":body},doc,int((time.monotonic()-t0)*1000),note)
            self._save();return JSONResponse(body if isinstance(body,dict) else {"detail":body},status_code=code,headers={"Cache-Control":"no-store"})
        with self.lock:
            mode=self.faults.get("resolver","ok")
            if mode=="notdeployed":return reply(404,"Not Found",note="Resolver not deployed (injected)")   # the route does not exist yet at CSIT
            if not self._auth_ok(request,READ_SCOPES):return reply(401,"service bearer required")
            d=next((x for x in self.docs.values() if x.get("sourceType")=="TestReport" and x.get("eventId")==event_id),None)
            if d is None:return reply(404,"no such Test Report outbox entry")
            job=self.jobs.get(d["outboxId"])
            if (document_id,version,km_job_id)!=(d["id"],str(d["version"]),job["kmJobId"] if job else None):
                if job:self.verdict(job,False,"KM asked the Correlation Resolver with values that do not match the notice it sent",d["name"])
                return reply(409,"correlation mismatch",d["id"])
            if d["stage"] in ("Deleting","Purged"):return reply(410,"document is being deleted",d["id"])
            if job["state"]!="Completed":
                self.verdict(job,False,"KM asked the Correlation Resolver before its v1 Completed status was recorded",d["name"])
                return reply(409,{"code":"job_not_completed"},d["id"])
            if mode=="unavailable":return reply(503,"temporarily unavailable (injected)",d["id"],"injected")
            job["resolverCalls"]+=1;self.verdict(job,True,"Correlation Resolver asked only after v1 Completed, with the exact ids",d["name"])
            self.ev(job,"KM 查詢 Correlation Resolver",{"sourceEntityId":d["entityId"],"csitJobId":d["outboxId"]})
            return reply(200,{"schemaVersion":"2.0","sourceSystem":"CSIT","sourceType":"TestReport","eventId":d["eventId"],"sourceEntityId":d["entityId"],
                "documentId":d["id"],"version":d["version"],"csitJobId":d["outboxId"],"kmJobId":job["kmJobId"],"sourceSha256":d["sha256"],"status":"Completed"},d["id"])

    def _receive_analysis(self,request,payload,answer):
        """POST /km/v2/analysis-results: judged against what CSIT knows, never against what KM could have guessed."""
        problems=check_analysis_result(payload)
        self.analyses.append({"t":self._now(),"payload":payload,"problems":problems})
        d=next((x for x in self.docs.values() if x.get("sourceType")=="TestReport" and isinstance(payload,dict) and x["id"]==payload.get("documentId")
                and x["version"]==payload.get("version")),None)
        if d is None:
            self.violations.append({"ref":None,"what":"analysis-results for an unknown Test Report document / version"});return answer(404,"unknown document",raise_=True)
        job=self.jobs[d["outboxId"]];self.ev(job,"KM→CSIT analysis-results",{"callbackId":payload.get("callbackId")})
        hdr=request.headers.get("idempotency-key");self.verdict(job,hdr==payload.get("callbackId"),"analysis-results carries Idempotency-Key = callbackId",d["name"])
        if problems:
            for pr in problems:self.verdict(job,False,"analysis-results: "+pr,d["name"])
            return answer(400,"; ".join(problems)[:300],d["id"],True)
        self.verdict(job,True,"analysis-results matches the spec",d["name"])
        bad=[f"{k} is {payload.get(k)!r}, CSIT's value is {want!r}" for k,want in (("sourceEntityId",d["entityId"]),("csitJobId",d["outboxId"]),("kmJobId",job["kmJobId"]),
              ("sourceSha256",d["sha256"])) if payload.get(k)!=want]
        if payload.get("csitJobId")==d["eventId"]:bad.append("csitJobId was filled with the v1 eventId (they are different ids)")
        if payload.get("sourceEntityId")==d["id"]:bad.append("sourceEntityId was filled with documentId (they are different ids)")
        if bad:
            for b in bad:self.verdict(job,False,"analysis-results correlation: "+b,d["name"])
            return answer(409,"correlation mismatch",d["id"],True)
        self.verdict(job,True,"analysis-results ids are the ones the Resolver gave (sourceEntityId, csitJobId, sourceSha256)",d["name"])
        if not job["resolverCalls"]:self.verdict(job,False,"analysis-results was sent without asking the Correlation Resolver (the ids must not be guessed)",d["name"])
        if d["stage"] in ("Deleting","Purged"):return answer(410,"document is being deleted",d["id"],True)
        if job["state"]!="Completed":
            self.verdict(job,False,"analysis-results arrived before the v1 Completed status",d["name"])
            from fastapi import HTTPException as H
            self.log("KM→CSIT","POST","/api/integrations/km/v2/analysis-results",409,payload,{"code":"job_not_completed"},d["id"],None);self._save()
            raise H(409,{"code":"job_not_completed"})
        cid=payload["callbackId"];canon=json.dumps(payload,sort_keys=True)
        if cid in self.seen:
            if self.seen[cid]==canon:self.ev(job,"重複的 callbackId(內容相同)→ 204");return answer(204,"duplicate, idempotent",d["id"])
            self.verdict(job,False,"same callbackId reused with a different body",d["name"]);return answer(409,"callbackId conflict",d["id"],True)
        self.seen[cid]=canon;d["analysis"]=payload["result"];self.ev(d,"KM 補送完整 AI 分析結果(analysis-results)","已存入 CSIT")
        return answer(204,None,d["id"])

    # ---------- documents ----------
    def _v2_fields(self,spec,d):
        st=spec.get("sourceType","DocumentLibraryFile")
        if st not in ("DocumentLibraryFile","TestReport") and st not in SOURCE_TYPES_V2:raise HTTPException(400,"unknown sourceType "+str(st))
        old=None
        if spec.get("supersedesDocId"):
            old=self.docs.get(spec["supersedesDocId"])
            if old is None or old["sourceType"]!=st:raise HTTPException(400,"supersedesDocId must name an existing document of the same source type")
        d.update(sourceType=st,version=int(spec.get("version") or ((old["version"]+1) if old else 1)),
                 entityId=str(uuid.uuid4()) if st in ("VerificationApplicationAttachment","TestReport") else d["id"],
                 applicationId=str(uuid.uuid4()) if st=="VerificationApplicationAttachment" else None,
                 vendorId=str(uuid.uuid4()) if st=="VendorFile" else None,equipmentId=str(uuid.uuid4()) if st=="EquipmentAttachment" else None,
                 supersedesDocId=old["id"] if old else None,revision=0,approval=None,archivedAt=None,changeIds=[],
                 eventId=str(uuid.uuid4()),outboxId=str(uuid.uuid4()),
                 project={"id":str(uuid.uuid4()),"number":"PRJ-001","name":"模擬專案"} if st=="TestReport" else None,
                 case={"id":str(uuid.uuid4()),"number":"CASE-001","name":"模擬測試案例"} if st=="TestReport" else None,
                 task={"id":str(uuid.uuid4()),"number":"TASK-001","name":"模擬測試任務"} if st=="TestReport" else None,
                 approvalMode="ApprovalBypassed" if spec.get("approvalBypass") else "Approved",
                 attributes={"tags":[],"keywords":[],"displayName":None,"modelNumbers":[],"vendorReference":None})

    def _dispatch_v2(self,d,new_job):
        with self.lock:
            if d["jobIds"] and not new_job:cid=d["jobIds"][-1]
            else:
                cid=str(uuid.uuid4())
                self.jobs[cid]={"csitJobId":cid,"eventId":str(uuid.uuid4()),"v2":True,"docId":d["id"],"kmJobId":None,"state":"New","callbacks":[],
                                "downloads":[],"verdicts":[],"timeline":[],"sendCount":0}
                d["jobIds"].append(cid)
        if d["stage"]=="Archived":d["stage"]="Dispatched"
        self._send_job_v2(d,self.jobs[cid]);self._save();return self.view(d)

    def _job_body(self,d,job):
        f=d["faults"];st=d["sourceType"]
        old=self.docs.get(d["supersedesDocId"]) if d["supersedesDocId"] else None
        return {"schemaVersion":"2.0","eventId":job["eventId"],"csitJobId":job["csitJobId"],"eventType":EVENT_TYPE[st],"sourceSystem":"CSIT",
            "source":{"type":st,"entityId":d["entityId"],"moduleCode":MODULE[st],"applicationId":d["applicationId"],"recordId":None,
                      "vendorId":d["vendorId"],"equipmentId":d["equipmentId"]},
            "document":{"id":d["id"],"version":d["version"],"originalFileName":d["name"],"contentType":d["contentType"],"sizeBytes":d["size"],
                        "sha256":"0"*64 if f["wrongDeclaredSha"] else d["sha256"],"downloadUrl":file_route(d,self.public_base),
                        "archivedAt":d["archivedAt"],"approval":d["approval"]},
            "classification":d["classification"],
            "supersedes":{"oldDocumentId":old["id"],"oldVersion":old["version"],"oldSha256":old["sha256"]} if old else None,
            "occurredAt":self._now()}

    def _send_job_v2(self,d,job):
        f=d["faults"];body=self._job_body(d,job)
        job["sendCount"]+=1;path=KM_V2+"/document-jobs"
        self.ev(job,"CSIT→KM v2 派送通知",f"第 {job['sendCount']} 次 · {d['sourceType']}")
        t0=time.monotonic()
        try:r=httpx.post(self.km+path,json=body,headers=self._headers(None if f["noIdempotencyKey"] else job["eventId"],f["badToken"],"jobs"),timeout=self.timeout)
        except httpx.HTTPError as e:
            self.log("CSIT→KM","POST",path,None,body,{"error":type(e).__name__},d["id"],note="KM 無法連線")
            self.ev(job,"KM 無法連線",type(e).__name__);self.verdict(job,False,"KM unreachable: "+type(e).__name__,d["name"]);return
        ms=int((time.monotonic()-t0)*1000)
        try:resp=r.json()
        except ValueError:resp=r.text[:400]
        self.log("CSIT→KM","POST",path,r.status_code,body,resp,d["id"],ms)
        self.ev(job,f"KM 回應 {r.status_code}",resp if r.status_code!=202 else None)
        if f["badToken"]:
            self.verdict(job,r.status_code==401,f"invalid bearer token is rejected with 401 (got {r.status_code})",d["name"])
        elif r.status_code==202:
            ok=isinstance(resp,dict) and resp.get("eventId")==job["eventId"] and resp.get("csitJobId")==job["csitJobId"] \
               and resp.get("status")=="Accepted" and bool(resp.get("kmJobId"))
            self.verdict(job,ok,"202 body is {eventId,csitJobId,kmJobId,status:Accepted}",d["name"])
            if job["kmJobId"]:
                same=isinstance(resp,dict) and resp.get("kmJobId")==job["kmJobId"]
                self.verdict(job,same,"resend returned the original kmJobId (idempotent)" if same else "resend returned a different kmJobId (must be idempotent)",d["name"])
            if isinstance(resp,dict):job["kmJobId"]=resp.get("kmJobId");d["kmJobId"]=resp.get("kmJobId")
            if job["state"]=="New":job["state"]="Accepted"
            if d["kmStatus"] is None:d["kmStatus"]="Accepted"
            self.ev(d,"KM 已受理(202)",job["kmJobId"])
        else:
            job["state"]="Rejected";d["kmStatus"]="Rejected"
            if d["stage"]=="Purged":
                self.verdict(job,r.status_code==410,f"a notice for a deleted version is refused with 410 (got {r.status_code})",d["name"])
            else:
                self.verdict(job,r.status_code in (409,410,422,503),f"KM refused the job with {r.status_code}",d["name"])
            self.ev(d,f"KM 拒絕通知({r.status_code})")

    # ---------- metadata change (spec 6.2) ----------
    def change_metadata(self,doc_id,spec):
        d=self._doc(doc_id)
        if not d["archived"] or d["stage"] in ("Deleting","Purged"):raise HTTPException(409,"only an archived, not deleted document can change metadata")
        if not d["jobIds"]:raise HTTPException(409,"dispatch first: KM knows the document only after the upload notice")
        before={"classification":d["classification"],"attributes":dict(d["attributes"])}
        cls=d["classification"]
        if "classification" in spec:
            from .sim import TAXONOMY,_find_class
            cls={l:(_find_class(spec["classification"].get(l),TAXONOMY) if spec["classification"].get(l) else None) for l in ("l1","l2","l3")}
        attrs=dict(d["attributes"])
        for k in ("tags","keywords","modelNumbers"):
            if k in spec:attrs[k]=[str(x) for x in spec[k]]
        for k in ("displayName","vendorReference"):
            if k in spec:attrs[k]=spec[k] or None
        changed=[]
        if cls!=before["classification"]:changed.append("classification")
        changed+=["attributes."+k for k in attrs if attrs[k]!=before["attributes"][k]]
        if not changed:raise HTTPException(409,"nothing changed")
        with self.lock:
            d["classification"]=cls;d["attributes"]=attrs;d["revision"]+=1
            cid=str(uuid.uuid4())
            x={"changeId":cid,"docId":d["id"],"revision":d["revision"],"kmChangeJobId":None,"state":"New","callbacks":[],"verdicts":[],"timeline":[]}
            self.changes[cid]=x;d["changeIds"].append(cid)
        self.ev(d,"使用者修改分類 / 標籤",f"revision {d['revision']} · {', '.join(changed)}")
        return self._send_change(x,changed)
    def _send_change(self,x,changed=None,bad_revision=None):
        d=self.docs[x["docId"]]
        body={"schemaVersion":"2.0","changeId":x["changeId"],"sourceSystem":"CSIT","sourceType":d["sourceType"],"sourceEntityId":d["entityId"],
              "documentId":d["id"],"version":d["version"],"sourceRevision":bad_revision or x["revision"],"occurredAt":self._now(),
              "classification":d["classification"],"attributes":d["attributes"],"changedFields":changed or x.get("changed") or []}
        x["changed"]=body["changedFields"];path=KM_V2+"/document-metadata-changes";self.ev(x,"CSIT→KM 分類/標籤變更")
        t0=time.monotonic()
        try:r=httpx.post(self.km+path,json=body,headers=self._headers(x["changeId"],False,"changes"),timeout=self.timeout)
        except httpx.HTTPError as e:
            self.log("CSIT→KM","POST",path,None,body,{"error":type(e).__name__},d["id"],note="KM 無法連線")
            self.verdict(x,False,"KM unreachable: "+type(e).__name__,d["name"]);self._save();return self.view(d)
        try:resp=r.json()
        except ValueError:resp=r.text[:400]
        self.log("CSIT→KM","POST",path,r.status_code,body,resp,d["id"],int((time.monotonic()-t0)*1000));self.ev(x,f"KM 回應 {r.status_code}")
        if bad_revision:
            self.verdict(x,r.status_code==409,f"a stale sourceRevision is refused with 409 (got {r.status_code})",d["name"])
        elif r.status_code==202:
            ok=isinstance(resp,dict) and resp.get("changeId")==x["changeId"] and resp.get("status")=="Accepted" and bool(resp.get("kmChangeJobId"))
            self.verdict(x,ok,"202 body is {changeId,kmChangeJobId,status:Accepted}",d["name"])
            if isinstance(resp,dict):x["kmChangeJobId"]=resp.get("kmChangeJobId")
            x["state"]="Accepted"
        else:
            x["state"]="Rejected";self.verdict(x,False,f"KM refused the change with {r.status_code}",d["name"])
        self._save();return self.view(d)
    def resend_stale_change(self,doc_id):
        """Send the previous revision again under a new changeId: KM must answer 409 (spec 6.2, older revision)."""
        d=self._doc(doc_id)
        if not d["changeIds"]:raise HTTPException(409,"no change was sent yet")
        last=self.changes[d["changeIds"][-1]]
        cid=str(uuid.uuid4())
        x={"changeId":cid,"docId":d["id"],"revision":last["revision"],"kmChangeJobId":None,"state":"New","callbacks":[],"verdicts":[],"timeline":[]}
        with self.lock:self.changes[cid]=x;d["changeIds"].append(cid)
        return self._send_change(x,last.get("changed"),bad_revision=last["revision"])

    # ---------- Test Report v1 deletion (the v1 route and reason codes stay as they were) ----------
    def _delete_report_v1(self,d,deletion_request_id):
        rid=deletion_request_id or str(uuid.uuid4())
        if rid in self.dels:return self._send_deletion(self.dels[rid])
        res={"sourceType":"TestReport","documentFileId":None,"documentId":d["id"],"version":d["version"],"sourceEntityId":d["entityId"],"applicationId":None,"recordId":None}
        x={"deletionRequestId":rid,"docId":d["id"],"resource":res,"reason":"TestReportVersionDeleted","kmDeletionJobId":None,"state":"New","callbacks":[],"verdicts":[],"timeline":[]}
        with self.lock:self.dels[rid]=x;d["delIds"].append(rid)
        d["stage"]="Deleting";d["deleteState"]="Requested";self.ev(d,"使用者刪除測試報告","v1 刪除通知;KM 驗證清理後 CSIT 才刪檔")
        return self._send_deletion(x)

    # ---------- v2 deletion (spec 7.2) ----------
    def _delete_v2(self,d,deletion_request_id):
        rid=deletion_request_id or str(uuid.uuid4())
        if rid in self.dels:return self._send_deletion_v2(self.dels[rid])
        job=self.jobs[d["jobIds"][-1]] if d["jobIds"] else None
        res={"sourceType":d["sourceType"],"sourceEntityId":d["entityId"],"documentId":d["id"],"version":d["version"],"sha256":d["sha256"],
             "applicationId":d["applicationId"],"recordId":None,"vendorId":d["vendorId"],"equipmentId":d["equipmentId"],
             "canonicalIngestionEventId":job["eventId"] if job else str(uuid.uuid4()),"scope":"DocumentVersion"}
        x={"deletionRequestId":rid,"docId":d["id"],"v2":True,"resource":res,"kmDeletionJobId":None,"state":"New","callbacks":[],"verdicts":[],"timeline":[]}
        with self.lock:self.dels[rid]=x;d["delIds"].append(rid)
        d["stage"]="Deleting";d["deleteState"]="Requested";self.ev(d,"使用者刪除文件","通知 KM(v2);KM 驗證清理完成後,CSIT 才刪自己的檔案")
        return self._send_deletion_v2(x)
    def _send_deletion_v2(self,x):
        d=self.docs[x["docId"]]
        body={"schemaVersion":"2.0","sourceSystem":"CSIT","eventType":"DocumentDeletionRequested","deletionRequestId":x["deletionRequestId"],
              "requestedAt":self._now(),"reasonCode":"SourceDeleted","resource":x["resource"]}
        path=KM_V2+"/document-deletions";self.ev(x,"CSIT→KM v2 刪除通知");t0=time.monotonic()
        try:r=httpx.post(self.km+path,json=body,headers=self._headers(x["deletionRequestId"],False,"deletions"),timeout=self.timeout)
        except httpx.HTTPError as e:
            self.log("CSIT→KM","POST",path,None,body,{"error":type(e).__name__},d["id"],note="KM 無法連線")
            self.verdict(x,False,"KM unreachable: "+type(e).__name__,d["name"]);self._save();return self.view(d)
        try:resp=r.json()
        except ValueError:resp=r.text[:400]
        self.log("CSIT→KM","POST",path,r.status_code,body,resp,d["id"],int((time.monotonic()-t0)*1000));self.ev(x,f"KM 回應 {r.status_code}")
        if r.status_code==202:
            ok=isinstance(resp,dict) and resp.get("deletionRequestId")==x["deletionRequestId"] and resp.get("status")=="Accepted" and bool(resp.get("kmDeletionJobId"))
            self.verdict(x,ok,"202 body is {deletionRequestId,kmDeletionJobId,status:Accepted}",d["name"])
            if isinstance(resp,dict):x["kmDeletionJobId"]=resp.get("kmDeletionJobId")
            x["state"]="Accepted";d["deleteState"]="Accepted";self.ev(d,"KM 已受理刪除(202)",x["kmDeletionJobId"])
        else:
            x["state"]="Rejected";self.verdict(x,False,f"KM refused the deletion with {r.status_code}",d["name"])
        self._save();return self.view(d)

    # ---------- what KM calls on CSIT ----------
    def receive_v2(self,request,payload,kind):
        """kind: jobs | changes | deletions | analysis. Same judging as the v1.3 callbacks, against the v1.4 contract."""
        t0=time.monotonic();path=V2_PATHS[kind]
        def answer(code,note=None,doc=None,raise_=False):
            self.log("KM→CSIT","POST",path,code,payload,{"note":note} if note else None,doc,int((time.monotonic()-t0)*1000));self._save()
            if raise_:raise HTTPException(code,note or "rejected")
            from fastapi import Response
            return Response(status_code=204)
        if not self._auth_ok(request,DELETION_SCOPES if kind=="deletions" else STATUS_SCOPES):return answer(401,"service bearer required",raise_=True)
        with self.lock:
            g=self.faults
            if g["callbackFailures"]>0:
                g["callbackFailures"]-=1;return answer(g["callbackStatus"],"injected CSIT failure",raise_=True)
            if kind=="analysis":return self._receive_analysis(request,payload,answer)
            table,checker,idkey=({"jobs":(self.jobs,check_job_callback_v2,"csitJobId"),"changes":(self.changes,check_change_callback,"changeId"),
                                  "deletions":(self.dels,check_deletion_callback_v2,"deletionRequestId")})[kind]
            problems=checker(payload)
            obj=table.get((payload or {}).get(idkey)) if isinstance(payload,dict) else None
            if obj is None:
                self.violations.append({"ref":None,"what":f"{kind} callback for an unknown {idkey}"});return answer(404,"unknown job",raise_=True)
            d=self.docs[obj["docId"]];status=payload.get("status");label={"jobs":"v2 ingestion","changes":"metadata change","deletions":"v2 deletion"}[kind]
            self.ev(obj,f"KM→CSIT 回報 {status}",{"callbackId":payload.get("callbackId")})
            hdr=request.headers.get("idempotency-key")
            self.verdict(obj,hdr==payload.get("callbackId"),f"{status} callback carries Idempotency-Key = callbackId",d["name"])
            if problems:
                for pr in problems:self.verdict(obj,False,f"{status} {label} callback: {pr}",d["name"])
                return answer(400,"; ".join(problems)[:300],d["id"],True)
            self.verdict(obj,True,f"{status} {label} callback matches the spec",d["name"])
            mismatch=self._correlation_problems(kind,obj,d,payload)
            if mismatch:
                for m in mismatch:self.verdict(obj,False,m,d["name"])
                return answer(409,"correlation mismatch",d["id"],True)
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
            self._apply_callback(kind,obj,d,payload,status)
            return answer(204,None,d["id"])
    def _correlation_problems(self,kind,obj,d,p):
        out=[]
        if kind=="jobs":
            for k,want in (("eventId",obj["eventId"]),("sourceType",d["sourceType"]),("sourceEntityId",d["entityId"]),("documentId",d["id"]),
                           ("version",d["version"]),("sourceSha256",d["sha256"])):
                if p.get(k)!=want:out.append(f"{k} does not match the accepted job (spec appendix C: echoed unchanged)")
            if obj.get("kmJobId") and p.get("kmJobId")!=obj["kmJobId"]:out.append("kmJobId differs from the one returned in the 202")
        elif kind=="changes":
            if obj.get("kmChangeJobId") and p.get("kmChangeJobId")!=obj["kmChangeJobId"]:out.append("kmChangeJobId differs from the one returned in the 202")
            if p.get("status")=="Completed" and p.get("appliedRevision")!=obj["revision"]:
                out.append(f"appliedRevision {p.get('appliedRevision')} must equal sourceRevision {obj['revision']}")
        else:
            if obj.get("kmDeletionJobId") and p.get("kmDeletionJobId")!=obj["kmDeletionJobId"]:out.append("kmDeletionJobId differs from the one returned in the 202")
            if p.get("resource")!=obj["resource"]:out.append("resource differs from the deletion request (must be identical)")
        return out
    def _apply_callback(self,kind,obj,d,p,status):
        if kind=="jobs":
            d["kmStatus"]=status
            if status=="Completed":d["result"]=p["result"];self.ev(d,"KM 完成:取得 AI Metadata","索引已持久化")
            elif status=="Failed":d["error"]=p["error"];self.ev(d,"KM 失敗",p["error"])
            else:self.ev(d,"KM 開始處理(Processing)")
        elif kind=="changes":
            if status=="Completed":d["appliedRevision"]=p["appliedRevision"];self.ev(d,"KM 已套用分類/標籤變更",f"revision {p['appliedRevision']}")
            elif status=="Failed":self.ev(d,"KM 套用變更失敗",p["error"])
        else:
            if status=="Completed":
                self.verdict(obj,True,"cleanupVerified=true with seven verified items",d["name"])
                d["stage"]="Purged";d["deleteState"]="Verified";d["content"]=None
                self.ev(d,"KM 驗證清理完成 → CSIT 才刪自己的檔案","CSIT NAS 檔案已移除")
                if self.dir:(self.dir/"content"/(d["id"]+".bin")).unlink(missing_ok=True)
            elif status=="Failed":d["deleteState"]="Failed";self.ev(d,"KM 刪除失敗",p["error"])
            else:d["deleteState"]="Processing";self.ev(d,"KM 開始清理(Processing)")
