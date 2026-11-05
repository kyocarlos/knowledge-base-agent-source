"""What CSIT would accept from KM, written from spec v1.3 only (independent of the KM implementation)."""
import re,uuid
from datetime import datetime

UUID_RE=re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
DOC_TYPES={"Specification","Manual","TestReport","SOP","MeetingMinutes","IssueAnalysis","Presentation","Other"}
CLEANUP=("metadata","extractedText","chunks","vectorIndex","graphRelations","cache","storedCopies")
RESULT_KEYS={
 "document":["title","documentType","summary","language","documentDate","authors","department","documentVersionLabel","keywords","tags"],
 "technical":["productNames","modelNumbers","vendorNames","technologies","standards","softwareVersions","hardwareVersions",
              "projectNames","testItems","measurements","issueKeys","errorCodes"],
 "extraction":["sourceFormat","method","pageCount","sheetNames","extractedCharacterCount","ocrUsed"],
 "indexing":["status","indexId","chunkCount","indexedAt"]}
LISTS={"document":{"authors","keywords","tags"},"technical":{"productNames","modelNumbers","vendorNames","technologies","standards",
    "softwareVersions","hardwareVersions","projectNames","testItems","measurements","issueKeys","errorCodes"},"extraction":{"sheetNames"}}

def _ts(v):
    if not isinstance(v,str):return False
    try:return datetime.fromisoformat(v.replace("Z","+00:00")).tzinfo is not None
    except ValueError:return False

def _envelope(p,id_keys,problems,schema="1.0"):
    for k in ("schemaVersion","callbackId","sourceSystem","status","timestamps","result","error",*id_keys):
        if k not in p:problems.append("missing key "+k)
    if p.get("schemaVersion")!=schema:problems.append("schemaVersion must be "+schema)
    if p.get("sourceSystem")!="CSIT":problems.append("sourceSystem must be CSIT")
    if not (isinstance(p.get("callbackId"),str) and UUID_RE.match(p["callbackId"])):problems.append("callbackId must be a UUID")
    ts=p.get("timestamps")
    if not isinstance(ts,dict) or set(ts)!={"startedAt","completedAt","failedAt"}:
        problems.append("timestamps must have exactly startedAt, completedAt, failedAt");ts={}
    else:
        for k,v in ts.items():
            if v is not None and not _ts(v):problems.append("timestamps."+k+" is not an ISO timestamp with zone")
    return ts

def check_ingestion_callback(p):
    problems=[]
    if not isinstance(p,dict):return ["body is not an object"]
    ts=_envelope(p,("documentFileId","csitJobId","kmJobId"),problems)
    for k in ("documentFileId","csitJobId"):
        if not (isinstance(p.get(k),str) and UUID_RE.match(p[k])):problems.append(k+" must be a UUID")
    if not isinstance(p.get("kmJobId"),str) or not p.get("kmJobId"):problems.append("kmJobId must be a non-empty string")
    status=p.get("status")
    if status=="Processing":
        if not ts.get("startedAt"):problems.append("Processing needs timestamps.startedAt")
        if p.get("result") is not None or p.get("error") is not None:problems.append("Processing needs result=null and error=null")
    elif status=="Failed":
        if not ts.get("failedAt"):problems.append("Failed needs timestamps.failedAt")
        e=p.get("error")
        if not isinstance(e,dict) or not {"code","message","retryable"}<=set(e) or not isinstance(e.get("retryable"),bool):
            problems.append("Failed needs error={code,message,retryable}")
        if p.get("result") is not None:problems.append("Failed needs result=null")
    elif status=="Completed":
        if not ts.get("completedAt"):problems.append("Completed needs timestamps.completedAt")
        if p.get("error") is not None:problems.append("Completed needs error=null")
        problems+=check_result(p.get("result"))
    else:problems.append("status must be Processing, Completed or Failed")
    return problems

def check_result(r,v2=False):
    if not isinstance(r,dict):return ["Completed.result is missing"]
    problems=[]
    want="2.0" if v2 else "1.0"
    if r.get("metadataSchemaVersion")!=want:problems.append("result.metadataSchemaVersion must be "+want)
    if v2 and not isinstance(r.get("sourceSpecific"),dict):problems.append("result.sourceSpecific must be an object (may be empty)")
    if not v2 and "sourceSpecific" in r:problems.append("v1 result has no sourceSpecific")
    for group,keys in RESULT_KEYS.items():
        g=r.get(group)
        if not isinstance(g,dict):problems.append("result."+group+" is missing");continue
        for k in keys:
            if k not in g:problems.append(f"result.{group}.{k} is missing (unknown must be null / [])")
        for k in LISTS.get(group,()):
            if k in g and not isinstance(g[k],list):problems.append(f"result.{group}.{k} must be an array")
        extra=set(g)-set(keys)
        if extra:problems.append(f"result.{group} has unknown keys {sorted(extra)}")
    if not isinstance(r.get("warnings"),list):problems.append("result.warnings must be an array")
    d=r.get("document") or {}
    if d.get("documentType") not in DOC_TYPES:problems.append("result.document.documentType is not an allowed value")
    x=r.get("extraction") or {}
    if x.get("method") not in ({"Text","OCR","Mixed","Visual","None"} if v2 else {"Text","OCR","Mixed"}):problems.append("result.extraction.method invalid")
    if x.get("ocrUsed") is True and x.get("method") not in ("OCR","Mixed"):problems.append("ocrUsed=true needs method OCR or Mixed")
    i=r.get("indexing") or {}
    if i.get("status")!="Completed":problems.append("result.indexing.status must be Completed")
    if not i.get("indexId"):problems.append("result.indexing.indexId must be non-empty")
    if not (isinstance(i.get("chunkCount"),int) and i["chunkCount"]>=0):problems.append("result.indexing.chunkCount must be an integer >= 0")
    if not _ts(i.get("indexedAt")):problems.append("result.indexing.indexedAt must be a UTC timestamp")
    return problems

def check_deletion_callback(p):
    problems=[]
    if not isinstance(p,dict):return ["body is not an object"]
    ts=_envelope(p,("deletionRequestId","kmDeletionJobId","resource"),problems)
    if not (isinstance(p.get("deletionRequestId"),str) and UUID_RE.match(p["deletionRequestId"])):problems.append("deletionRequestId must be a UUID")
    status=p.get("status")
    if status=="Processing":
        if not ts.get("startedAt"):problems.append("Processing needs timestamps.startedAt")
    elif status=="Failed":
        if not ts.get("failedAt"):problems.append("Failed needs timestamps.failedAt")
        if not isinstance(p.get("error"),dict):problems.append("Failed needs an error object")
    elif status=="Completed":
        if not ts.get("completedAt"):problems.append("Completed needs timestamps.completedAt")
        res=p.get("result")
        if not isinstance(res,dict) or res.get("cleanupVerified") is not True:problems.append("Completed needs result.cleanupVerified=true")
        else:
            if not _ts(res.get("verifiedAt")):problems.append("result.verifiedAt must be a timestamp")
            c=res.get("cleanup")
            if not isinstance(c,dict) or set(c)!=set(CLEANUP):problems.append("result.cleanup needs exactly the seven items")
            else:
                for k,v in c.items():
                    if v not in ("Deleted","NotPresent"):problems.append(f"cleanup.{k} must be Deleted or NotPresent, got {v!r}")
    else:problems.append("status must be Processing, Completed or Failed")
    return problems


# ---------------- spec v1.4 ----------------
SOURCE_TYPES_V2=("VerificationApplicationAttachment","VendorFile","EquipmentAttachment")

def _sha(v):return isinstance(v,str) and re.fullmatch(r"[0-9a-f]{64}",v) is not None

def _error_ok(p,problems):
    e=p.get("error")
    if not isinstance(e,dict) or not {"code","message","retryable"}<=set(e) or not isinstance(e.get("retryable"),bool) or not e.get("code"):
        problems.append("Failed needs error={code,message,retryable}")

def check_job_callback_v2(p):
    """POST /km/v2/document-jobs/status (spec 5.1-5.3)."""
    problems=[]
    if not isinstance(p,dict):return ["body is not an object"]
    ts=_envelope(p,("eventId","csitJobId","kmJobId","sourceType","sourceEntityId","documentId","version","sourceSha256"),problems,"2.0")
    for k in ("eventId","csitJobId","sourceEntityId","documentId"):
        if not (isinstance(p.get(k),str) and UUID_RE.match(p[k])):problems.append(k+" must be a UUID")
    if not isinstance(p.get("kmJobId"),str) or not p.get("kmJobId"):problems.append("kmJobId must be a non-empty string")
    if p.get("sourceType") not in SOURCE_TYPES_V2:problems.append("sourceType is not a registered source")
    if not (isinstance(p.get("version"),int) and not isinstance(p.get("version"),bool) and p["version"]>=1):problems.append("version must be an integer >= 1")
    if not _sha(p.get("sourceSha256")):problems.append("sourceSha256 must be 64 lowercase hex")
    status=p.get("status")
    if status=="Processing":
        if not ts.get("startedAt"):problems.append("Processing needs timestamps.startedAt")
        if p.get("result") is not None or p.get("error") is not None:problems.append("Processing needs result=null and error=null")
    elif status=="Failed":
        if not ts.get("failedAt"):problems.append("Failed needs timestamps.failedAt")
        _error_ok(p,problems)
        if p.get("result") is not None:problems.append("Failed needs result=null")
    elif status=="Completed":
        if not ts.get("completedAt"):problems.append("Completed needs timestamps.completedAt")
        if p.get("error") is not None:problems.append("Completed needs error=null")
        problems+=check_result(p.get("result"),v2=True)
    else:problems.append("status must be Processing, Completed or Failed")
    return problems

def check_change_callback(p):
    """POST /km/v2/document-metadata-changes/status (spec 6.2)."""
    problems=[]
    if not isinstance(p,dict):return ["body is not an object"]
    for k in ("schemaVersion","callbackId","changeId","kmChangeJobId","sourceSystem","status","appliedRevision","timestamps","error"):
        if k not in p:problems.append("missing key "+k)
    if p.get("schemaVersion")!="2.0":problems.append("schemaVersion must be 2.0")
    for k in ("callbackId","changeId"):
        if not (isinstance(p.get(k),str) and UUID_RE.match(p[k])):problems.append(k+" must be a UUID")
    ts=p.get("timestamps")
    if not isinstance(ts,dict) or set(ts)!={"startedAt","completedAt","failedAt"}:problems.append("timestamps must have exactly startedAt, completedAt, failedAt");ts={}
    status=p.get("status")
    if status=="Processing":
        if not ts.get("startedAt"):problems.append("Processing needs timestamps.startedAt")
    elif status=="Failed":
        if not ts.get("failedAt"):problems.append("Failed needs timestamps.failedAt")
        _error_ok(p,problems)
    elif status=="Completed":
        if not ts.get("completedAt"):problems.append("Completed needs timestamps.completedAt")
        if not (isinstance(p.get("appliedRevision"),int) and p["appliedRevision"]>=1):problems.append("Completed needs appliedRevision >= 1")
        if p.get("error") is not None:problems.append("Completed needs error=null")
    else:problems.append("status must be Processing, Completed or Failed")
    return problems

def check_deletion_callback_v2(p):
    """POST /km/v2/document-deletions/status (spec 7.2-7.3)."""
    problems=[]
    if not isinstance(p,dict):return ["body is not an object"]
    problems+=[x for x in check_deletion_callback({**p,"schemaVersion":"1.0"})]
    if p.get("schemaVersion")!="2.0":problems.append("schemaVersion must be 2.0")
    return [x for x in problems if x!="schemaVersion must be 1.0"]

def check_analysis_result(p):
    """POST /km/v2/analysis-results (spec 5.4)."""
    problems=[]
    if not isinstance(p,dict):return ["body is not an object"]
    for k in ("schemaVersion","analysisResultId","callbackId","sourceSystem","sourceType","sourceEntityId","documentId","version","csitJobId","kmJobId",
              "sourceSha256","metadataSchemaVersion","result","analyzedAt","supersedesAnalysisResultId"):
        if k not in p:problems.append("missing key "+k)
    if p.get("schemaVersion")!="2.0":problems.append("schemaVersion must be 2.0")
    if p.get("sourceType")!="TestReport":problems.append("sourceType must be TestReport")
    for k in ("analysisResultId","callbackId","sourceEntityId","documentId","csitJobId"):
        if not (isinstance(p.get(k),str) and UUID_RE.match(p[k])):problems.append(k+" must be a UUID")
    if not _sha(p.get("sourceSha256")):problems.append("sourceSha256 must be 64 lowercase hex")
    if not _ts(p.get("analyzedAt")):problems.append("analyzedAt must be a timestamp")
    problems+=check_result(p.get("result"),v2=True)
    return problems
