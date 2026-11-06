"""Drill a DEPLOYED KM through the running simulator (KM in sim mode: see deploy/csit-mode).

    SIM_URL=http://csit-sim:8765 QDRANT_URL=http://km-da40-qdrant-1:6333 QDRANT_COLLECTION=km_csit_docs_sim python -m tools.csit_simulator.remote_drill [--slow]

Same checks as drill.py (v1.3, v1.4 and v1.4.1), but KM is the real deployment (real Qdrant, real parsers, real retry delays), so the vector store is read over HTTP and the
checks that need minutes of real retry waiting (CSIT outage while KM reports) run only with --slow.
"""
import os,sys,time
import httpx

SLOW="--slow" in sys.argv
S=os.environ.get("SIM_URL","http://127.0.0.1:8765")
Q=os.environ.get("QDRANT_URL");COLL=os.environ.get("QDRANT_COLLECTION","km_csit_docs_sim")

def _scroll(flt=None):
    off=None
    while True:
        body={"limit":256,"with_payload":True,"offset":off}
        if flt:body["filter"]=flt
        r=httpx.post(f"{Q}/collections/{COLL}/points/scroll",json=body,timeout=30).json()["result"]
        yield from r["points"]
        off=r.get("next_page_offset")
        if off is None:return

def vids():
    """Id (document_file_id for v1.3 files, document_id for everything else) of every point in the simulated KM's collection (None without a vector store)."""
    if not Q:return None
    return {p["payload"].get("document_file_id") or p["payload"].get("document_id") for p in _scroll()}

def vstate():
    """id -> index_state ('Active' unless a replacement retired it)."""
    return {(p["payload"].get("document_file_id") or p["payload"].get("document_id")):p["payload"].get("index_state","Active") for p in _scroll()}

def vpayloads(doc_id):
    return [p["payload"] for p in _scroll({"must":[{"key":"document_id","match":{"value":doc_id}}]})]


def wait(cond,seconds=120):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if cond():return True
        time.sleep(.1)
    return False

def main():
    ping=httpx.get(S+"/api/km/ping",timeout=20).json()
    print("KM ping:",ping,flush=True)
    if not ping.get("ok") or '"csitMode":"sim"' not in ping.get("body","").replace(" ",""):sys.exit("KM is not reachable or not in sim mode: run csit-mode.sh sim first")
    post=lambda p,b=None:httpx.post(S+p,json=b if b is not None else {},timeout=30)
    docs=lambda:{d["id"]:d for d in httpx.get(S+"/api/state").json()["docs"]}
    doc=lambda i:docs()[i]
    kms=lambda i:doc(i)["kmStatus"]
    text="CSIT 測試文件。This manual describes the Wi-Fi 7 access point setup procedure. "*8
    results=[]
    def check(name,ok,note=""):
        results.append((name,bool(ok)));print(("PASS  " if ok else "FAIL  ")+name+(("  -- "+str(note)[:300]) if note and not ok else ""),flush=True)
    def new(name="manual.txt",body=None,**kw):return post("/api/docs",{"fileName":name,"contentText":body or text,**kw}).json()
    final=lambda i,t=120:wait(lambda:kms(i) in ("Completed","Failed","Rejected"),t)
    bad=lambda i:[v for v in doc(i)["allVerdicts"] if not v["ok"]]

    # 0 the CSIT workflow itself: KM is told only after approve -> NAS archive
    a=new();ia=a["id"]
    check("0 a pending upload has not reached KM",a["jobIds"]==[] and a["stage"]=="PendingApproval")
    check("0 dispatch before NAS archive is refused",post(f"/api/docs/{ia}/dispatch").status_code==409)
    post(f"/api/docs/{ia}/advance");post(f"/api/docs/{ia}/advance")
    check("0 approve then archive: still nothing sent",doc(ia)["archived"] and doc(ia)["jobIds"]==[])
    post(f"/api/docs/{ia}/advance")

    # 1 happy path
    check("1 KM accepts (202) then completes",final(ia) and kms(ia)=="Completed",kms(ia))
    j=doc(ia)["jobs"][-1]
    check("1 callbacks are Processing -> Completed",j["callbackStatuses"]==["Processing","Completed"],j["callbackStatuses"])
    check("1 every verdict passes",not bad(ia),bad(ia))
    r=j["result"] or {}
    check("1 metadata: all keys present, documentType from the allowed list",r.get("document",{}).get("documentType") in ("Specification","Manual","TestReport","SOP","MeetingMinutes","IssueAnalysis","Presentation","Other") and r.get("indexing",{}).get("chunkCount",0)>0 and r["indexing"].get("indexId"),r.get("document"))
    check("1 every keyword (if any) really occurs in the text",all(k.lower() in text.lower() for k in (r["document"]["keywords"] or [])))
    check("1 vectors stamped with the file id",vids() is None or ia in vids())

    # 2 resend (same job) and a second job
    again=post(f"/api/docs/{ia}/dispatch").json()
    check("2 resend keeps the csitJobId and the original kmJobId",len(again["jobs"])==1 and again["jobs"][0]["kmJobId"]==j["kmJobId"] and not bad(ia),bad(ia))

    # 3 sha mismatch
    b=new("tampered.txt",downloadFault="tamper",autoRun=True);ib=b["id"]
    check("3 altered bytes -> Failed, SHA256_MISMATCH, not retried",final(ib) and kms(ib)=="Failed" and doc(ib)["jobs"][-1]["error"]["code"]=="SHA256_MISMATCH"
          and doc(ib)["jobs"][-1]["error"]["retryable"] is False,doc(ib)["jobs"][-1].get("error"))
    check("3 only one download, no vectors",len(doc(ib)["jobs"][-1]["downloads"])==1 and (vids() is None or ib not in vids()))
    c=new("wrongsha.txt",wrongDeclaredSha=True,autoRun=True);ic=c["id"]
    check("3b wrong declared sha256 in the notice -> Failed SHA256_MISMATCH",final(ic) and doc(ic)["jobs"][-1]["error"]["code"]=="SHA256_MISMATCH",doc(ic)["jobs"][-1].get("error"))

    # 4 transient failure
    d=new("flaky.txt",downloadFault="unavailable",downloadFailures=2,autoRun=True);idd=d["id"]
    check("4 two 503s then Completed",final(idd,300) and kms(idd)=="Completed",kms(idd))
    check("4 no status regress",doc(idd)["jobs"][-1]["callbackStatuses"]==["Processing","Completed"],doc(idd)["jobs"][-1]["callbackStatuses"])
    check("4 three download attempts",len(doc(idd)["jobs"][-1]["downloads"])==3)

    # 5 bad token
    e=new("badtoken.txt",badToken=True,autoRun=True)
    check("5 wrong bearer rejected with 401",not bad(e["id"]) and doc(e["id"])["kmStatus"] is None,bad(e["id"]))

    # 6 CSIT outage while KM reports (callback retry delays are 10 s, 60 s, 300 s: several minutes)
    if SLOW:
        post("/api/callback-faults",{"callbackFailures":2,"callbackStatus":503})
        f=new("outage.txt",autoRun=True);iff=f["id"]
        check("6 callbacks survive a CSIT 503 outage",final(iff,600) and kms(iff)=="Completed",kms(iff))
        check("6 order kept after retries",doc(iff)["jobs"][-1]["callbackStatuses"]==["Processing","Completed"],doc(iff)["jobs"][-1]["callbackStatuses"])
        post("/api/callback-faults",{"callbackFailures":0,"callbackStatus":503})
    else:print("SKIP  6 CSIT outage while KM reports (use --slow)")

    # 7 unsupported format
    g=new("tool.exe","MZ binary",autoRun=True);ig=g["id"]
    check("7 unsupported format -> Failed without download",final(ig) and doc(ig)["jobs"][-1]["error"]["code"]=="UNSUPPORTED_DOCUMENT_FORMAT" and not doc(ig)["jobs"][-1]["downloads"])

    # 8 deletion of one of two same-name files
    h1=new("same.txt",text+"one",autoRun=True);h2=new("same.txt",text+"two",autoRun=True)
    final(h1["id"]);final(h2["id"])
    dl=post(f"/api/docs/{h1['id']}/delete").json()
    check("8 deletion accepted with 202",dl["dels"][0]["state"]=="Accepted" and not [v for v in dl["dels"][0]["verdicts"] if not v["ok"]])
    check("8 CSIT keeps its file until KM verifies cleanup (stage Deleting or Purged)",doc(h1["id"])["stage"] in ("Deleting","Purged"))
    check("8 deletion reaches Completed and CSIT then purges its file",wait(lambda:doc(h1["id"])["stage"]=="Purged"),doc(h1["id"])["stage"])
    dd=doc(h1["id"])["dels"][0]
    check("8 callbacks Processing -> Completed, verdicts pass",dd["callbackStatuses"]==["Processing","Completed"] and not bad(h1["id"]),dd["callbackStatuses"])
    check("8 only the targeted file is gone",vids() is None or (h1["id"] not in vids() and h2["id"] in vids()))
    cl=(dd["result"] or {}).get("cleanup",{})
    check("8 cleanup: chunks Deleted, graphRelations NotPresent",cl.get("chunks")=="Deleted" and cl.get("graphRelations")=="NotPresent",cl)

    # 9 deletion idempotent; no resurrection
    again=post(f"/api/docs/{h1['id']}/delete",{"deletionRequestId":dd["deletionRequestId"]}).json()
    check("9 same deletionRequestId returns the same kmDeletionJobId",again["dels"][0]["kmDeletionJobId"]==dd["kmDeletionJobId"])
    late=post(f"/api/docs/{h1['id']}/dispatch").json()
    check("9 late upload notice for a deleted file is refused",late["jobs"][-1]["state"]=="Rejected",late["jobs"][-1]["timeline"][-1:])
    check("9 nothing was re-indexed",vids() is None or h1["id"] not in vids())

    # ---------- spec v1.4: the three new sources, every format, replacement, metadata change, v2 deletion ----------
    import base64
    if not Q:sys.exit("the v1.4 checks read the vector store: set QDRANT_URL")
    SRC=("VerificationApplicationAttachment","VendorFile","EquipmentAttachment")
    fetched=lambda i:[t for t in httpx.get(S+"/api/traffic").json() if t["direction"]=="KM→CSIT" and t["method"]=="GET" and t["docId"]==i]
    v2={}
    for st in SRC:
        x=new(st[:6]+".txt",text,sourceType=st,autoRun=True);v2[st]=x["id"]
    for st in SRC:
        i=v2[st];ok=final(i) and kms(i)=="Completed"
        check("10 "+st+": KM accepts, fetches and completes",ok,kms(i))
        j=doc(i)["jobs"][-1]
        check("10 "+st+": callbacks Processing -> Completed, every verdict passes",j["callbackStatuses"]==["Processing","Completed"] and not bad(i),bad(i) or j["callbackStatuses"])
        got=[t["path"] for t in fetched(i)]
        check("10 "+st+": KM fetched the file from the route for this source ("+doc(i)["downloadPath"].split("/v1/")[-1].split("/")[0]+")",got and got[0]==doc(i)["downloadPath"],got)
        r=j["result"] or {}
        check("10 "+st+": result is v2 with sourceSpecific",r.get("metadataSchemaVersion")=="2.0" and isinstance(r.get("sourceSpecific"),dict),r.get("metadataSchemaVersion"))
        check("10 "+st+": points carry the exact source identity",i in vids())
    # two attachments, same name and same bytes, are two jobs (spec 10)
    t1=new("same.txt",text,sourceType="VerificationApplicationAttachment",autoRun=True);t2=new("same.txt",text,sourceType="VerificationApplicationAttachment",autoRun=True)
    check("10 same name + same SHA256 from two attachments: two jobs, both Completed",final(t1["id"]) and final(t2["id"]) and kms(t1["id"])==kms(t2["id"])=="Completed"
          and doc(t1["id"])["jobs"][0]["kmJobId"]!=doc(t2["id"])["jobs"][0]["kmJobId"])

    # 11 formats: nothing is skipped; unreadable ones fail with a code
    def fmt(name,raw,st="EquipmentAttachment"):
        return new(name,sourceType=st,contentBase64=base64.b64encode(raw).decode(),autoRun=True)["id"]
    md=fmt("notes.md",b"# FSW26 notes\nspectrum analyzer calibration steps\n")
    check("11 markdown completes",final(md) and kms(md)=="Completed",doc(md)["jobs"][-1].get("error"))
    png=fmt("photo.png",b"\x89PNG\r\n\x1a\n"+b"0"*60)
    check("11 an image is accepted, then Failed UNSUPPORTED_FORMAT, never downloaded",final(png) and doc(png)["jobs"][-1]["error"]["code"]=="UNSUPPORTED_FORMAT" and not fetched(png),doc(png)["jobs"][-1].get("error"))
    enc=fmt("locked.xlsx",b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"+b"0"*60)
    check("11 a password-protected workbook -> Failed ENCRYPTED_DOCUMENT",final(enc) and doc(enc)["jobs"][-1]["error"]["code"]=="ENCRYPTED_DOCUMENT",doc(enc)["jobs"][-1].get("error"))
    exe=fmt("run.txt",b"MZ"+b"0"*60)
    check("11 executable content -> Failed MALWARE_DETECTED",final(exe) and doc(exe)["jobs"][-1]["error"]["code"]=="MALWARE_DETECTED",doc(exe)["jobs"][-1].get("error"))
    check("11 every failure was judged against the spec",not (bad(png) or bad(enc) or bad(exe)),bad(png) or bad(enc) or bad(exe))

    # 12 replacement: the old index goes only after the new one is Completed
    old=v2["VendorFile"]
    nv=new("vendor-v2.txt",text+" revised edition",sourceType="VendorFile",supersedesDocId=old,autoRun=True)["id"]
    check("12 the replacement completes",final(nv) and kms(nv)=="Completed",kms(nv))
    check("12 the old version's index is retired, the new one is active",wait(lambda:vstate().get(old)=="Superseded") and vstate().get(nv)=="Active",vstate())
    bad_new=new("vendor-v3.exe","MZ not a document",sourceType="VendorFile",supersedesDocId=nv,autoRun=True)["id"]
    final(bad_new);time.sleep(.5)
    check("12 a replacement that fails leaves the previous index active",kms(bad_new)=="Failed" and vstate().get(nv)=="Active",vstate())

    # 13 metadata change: no re-fetch, index filters updated, revision reported
    eq=v2["EquipmentAttachment"];before=len(fetched(eq))
    r=post(f"/api/docs/{eq}/change",{"classification":{"l1":"10","l2":"11"},"tags":["wifi","fsw"],"displayName":"FSW26 guide"})
    check("13 the change is accepted (202)",r.status_code==200 and doc(eq)["changes"][-1]["state"] in ("Accepted","Processing","Completed"),r.text[:200])
    check("13 KM reports Completed with appliedRevision = sourceRevision",wait(lambda:doc(eq)["changes"][-1]["state"]=="Completed") and not bad(eq),bad(eq))
    pl=vpayloads(eq)
    check("13 the index payload carries the new classification and tags",pl and all(p.get("tags")==["wifi","fsw"] and p["classification"]["l1"]=="設備儀器專區" for p in pl),pl[:1])
    check("13 the zone follows the changed L1 (設備儀器專區)",pl and all(p.get("zone_id")=="equipment" and p.get("topic_zone")=="設備儀器專區" for p in pl),[(p.get("zone_id"),p.get("topic_zone")) for p in pl[:1]])
    check("13 the file was not fetched again",len(fetched(eq))==before)
    post(f"/api/docs/{eq}/stale-change")
    check("13 an older revision is refused with 409",not bad(eq) and any("stale" in v["what"] and v["ok"] for v in doc(eq)["allVerdicts"]),bad(eq))

    # 14 v2 deletion
    vd=v2["VendorFile"];dl=post(f"/api/docs/{vd}/delete").json()
    check("14 v2 deletion accepted with 202",dl["dels"][0]["state"]=="Accepted" and not bad(vd),bad(vd))
    check("14 KM verifies the cleanup, then CSIT purges its file",wait(lambda:doc(vd)["stage"]=="Purged"),doc(vd)["stage"])
    dd=doc(vd)["dels"][0]
    check("14 callbacks Processing -> Completed, resource echoed unchanged, every verdict passes",dd["callbackStatuses"]==["Processing","Completed"] and not bad(vd),bad(vd))
    cl=(dd["result"] or {}).get("cleanup",{})
    check("14 seven cleanup items, chunks Deleted, graphRelations NotPresent",len(cl)==7 and cl.get("chunks")=="Deleted" and cl.get("graphRelations")=="NotPresent",cl)
    check("14 the index of that version is gone",vd not in vids())
    late=post(f"/api/docs/{vd}/dispatch").json()
    check("14 a late upload notice for the deleted version is refused with 410",late["jobs"][-1]["state"]=="Rejected" and not bad(vd),bad(vd))
    check("14 nothing was re-indexed",vd not in vids())

    # ---------- spec v1.4.1: Test Report v1 + Correlation Resolver + analysis-results, replacement events, 409 policy ----------
    traffic=lambda:httpx.get(S+"/api/traffic").json()
    tr=new("report.txt",text+" throughput 9.2 Gbps",sourceType="TestReport",autoRun=True)["id"]
    check("15 Test Report: KM accepts the v1 notice, fetches the file and reports Completed on v1",final(tr) and kms(tr)=="Completed",kms(tr))
    jt=doc(tr)["jobs"][-1]
    check("15 v1 callbacks are Processing -> Completed, with no result in them",jt["callbackStatuses"]==["Processing","Completed"] and not bad(tr),bad(tr))
    check("15 KM fetched it from the documents route, once",[t["path"] for t in traffic() if t["direction"]=="KM→CSIT" and t["method"]=="GET" and t["docId"]==tr][:1]==[doc(tr)["downloadPath"]])
    check("15 the full result arrives afterwards in v2 analysis-results",wait(lambda:bool(doc(tr).get("analysis"))),[v for v in doc(tr)["allVerdicts"] if not v["ok"]])
    check("15 KM asked the Correlation Resolver (after v1 Completed) and used the ids it returned",not bad(tr) and any("Correlation Resolver asked only after v1 Completed" in v["what"] for v in doc(tr)["allVerdicts"]),bad(tr))
    check("15 sourceEntityId is not documentId and csitJobId is not eventId in what KM sent",any("ids are the ones the Resolver gave" in v["what"] and v["ok"] for v in doc(tr)["allVerdicts"]))
    ar=doc(tr).get("analysis") or {}
    check("15 the analysis result is v2 metadata with sourceSpecific, documentType TestReport, indexed",ar.get("metadataSchemaVersion")=="2.0" and ar.get("sourceSpecific") is not None
          and ar["document"]["documentType"]=="TestReport" and ar["indexing"]["chunkCount"]>0,ar.get("document"))

    # 16 the Resolver is not deployed yet: KM must not guess and must not send analysis-results
    post("/api/callback-faults",{"resolver":"notdeployed"})
    tr2=new("report2.txt",text+" second report",sourceType="TestReport",autoRun=True)["id"]
    check("16 the v1 flow completes even without the Resolver",final(tr2) and kms(tr2)=="Completed",kms(tr2))
    check("16 KM asks the Resolver and gets 404",wait(lambda:any(t["method"]=="GET" and "test-report-correlations" in t["path"] and t["status"]==404 for t in traffic())))
    time.sleep(8)
    sent=[t for t in traffic() if t["method"]=="POST" and t["path"].endswith("/analysis-results") and (t["request"] or {}).get("documentId")==tr2]
    check("16 no analysis-results for it, and no guessed ids",not sent and not doc(tr2).get("analysis") and not bad(tr2),sent[:1])
    post("/api/callback-faults",{"resolver":"ok"})

    # 17 replacement events: TestReportCommitted / DocumentLibraryFileUploaded on the v2 route, with supersedes
    tn=new("report-v2.txt",text+" revised report",sourceType="TestReport",supersedesDocId=tr,autoRun=True)["id"]
    check("17 a replacement Test Report goes on the v2 route and completes",final(tn) and kms(tn)=="Completed" and not bad(tn),bad(tn) or kms(tn))
    posts=[t for t in traffic() if t["method"]=="POST" and t["path"].endswith("/v2/document-jobs") and (t["request"] or {}).get("document",{}).get("id")==tn]
    check("17 its eventType is TestReportCommitted and it names supersedes",posts and posts[0]["request"]["eventType"]=="TestReportCommitted" and posts[0]["request"]["supersedes"]["oldDocumentId"]==tr)
    check("17 the old report's index (written through v1) is retired, the new one is active",wait(lambda:vstate().get(tr)=="Superseded") and vstate().get(tn)=="Active",vstate())
    lib=new("lib-old.txt",text+" library one",autoRun=True)["id"];final(lib)
    ln=new("lib-new.txt",text+" library two",sourceType="DocumentLibraryFile",supersedesDocId=lib,autoRun=True)["id"]
    check("17 a replacement library file goes on the v2 route as DocumentLibraryFileUploaded",final(ln) and kms(ln)=="Completed" and not bad(ln),bad(ln))
    check("17 the previous library file's index is retired",wait(lambda:vstate().get(lib)=="Superseded") and vstate().get(ln)=="Active",vstate())

    # 18 a 409 on a v2 status callback is not retried
    post("/api/callback-faults",{"callbackFailures":1,"callbackStatus":409})
    v409=new("conflict.txt",text,sourceType="VendorFile",autoRun=True)["id"]
    check("18 the job still completes",final(v409) and kms(v409)=="Completed",kms(v409))
    procs=[t for t in traffic() if t["method"]=="POST" and t["path"].endswith("/v2/document-jobs/status") and (t["request"] or {}).get("documentId")==v409 and (t["request"] or {}).get("status")=="Processing"]
    check("18 the refused Processing callback was sent once and not repeated",len(procs)==1 and procs[0]["status"]==409,[(t["status"]) for t in procs])

    # 19 an empty extraction is not a success
    blank=new("blank.txt","   \n   ",sourceType="VendorFile",autoRun=True)["id"]
    check("19 a file with no extractable text -> Failed EMPTY_EXTRACTION, retryable=false",final(blank) and doc(blank)["jobs"][-1]["error"]["code"]=="EMPTY_EXTRACTION"
          and doc(blank)["jobs"][-1]["error"]["retryable"] is False and not bad(blank),doc(blank)["jobs"][-1].get("error"))

    rep=httpx.get(S+"/api/report").json()
    unexpected=[v for v in rep["violations"] if "unreachable" in v["what"]]
    check("overall: no KM spec violations recorded",not unexpected and not [v for v in rep["violations"] if "refused" not in v["what"] and "rejected" not in v["what"]],rep["violations"])
    badr=[r for r in results if not r[1]]
    print(f"\n{len(results)-len(badr)}/{len(results)} checks passed")
    sys.exit(1 if badr else 0)

if __name__=="__main__":main()
