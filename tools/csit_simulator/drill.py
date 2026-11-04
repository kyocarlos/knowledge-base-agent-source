"""End-to-end drill: simulator (as CSIT) <-> real KM routes + real worker over real HTTP.

    TEST_DATABASE_URL=postgresql://... python -m tools.csit_simulator.drill

KM here is the production code on a local PostgreSQL (see km_local.py). To drill a deployed KM instead, start `serve` against it
and drive the UI or the /api/* routes yourself.
"""
import os,sys,tempfile,time,uuid
from pathlib import Path
import httpx,psycopg
from psycopg import sql
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.csit_simulator.km_local import LocalKm,free_port,serve
from tools.csit_simulator.sim import Sim
from tools.csit_simulator.app import create_app

TOKEN="drill-token"

def wait(cond,seconds=20):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if cond():return True
        time.sleep(.1)
    return False

def main():
    raw=os.environ.get("TEST_DATABASE_URL") or sys.exit("set TEST_DATABASE_URL to a PostgreSQL server you may create a schema in")
    sim_port,km_port=free_port(),free_port()
    sim=Sim(f"http://127.0.0.1:{km_port}",TOKEN);serve(create_app(sim),sim_port)
    km=LocalKm(raw,f"http://127.0.0.1:{sim_port}",TOKEN,km_port,retry_delays=(0,0),callback_delays=(0,0,0,0),poll=.1)
    S=f"http://127.0.0.1:{sim_port}"
    post=lambda p,b=None:httpx.post(S+p,json=b if b is not None else {},timeout=30)
    docs=lambda:{d["id"]:d for d in httpx.get(S+"/api/state").json()["docs"]}
    doc=lambda i:docs()[i]
    kms=lambda i:doc(i)["kmStatus"]
    text="CSIT 測試文件。This manual describes the Wi-Fi 7 access point setup procedure. "*8
    results=[]
    def check(name,ok,note=""):
        results.append((name,bool(ok)));print(("PASS  " if ok else "FAIL  ")+name+(("  -- "+str(note)[:300]) if note and not ok else ""),flush=True)
    def new(name="manual.txt",body=None,**kw):return post("/api/docs",{"fileName":name,"contentText":body or text,**kw}).json()
    final=lambda i:wait(lambda:kms(i) in ("Completed","Failed","Rejected"))
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
    check("1 metadata: documentType/summary/keywords present and from the document",r.get("document",{}).get("documentType")=="Manual" and r["document"]["summary"] and r["document"]["keywords"],r.get("document"))
    check("1 every keyword really occurs in the text",all(k.lower() in text.lower() for k in r["document"]["keywords"]))
    check("1 vectors stamped with the file id",ia in km.q.ids())

    # 2 resend (same job) and a second job
    again=post(f"/api/docs/{ia}/dispatch").json()
    check("2 resend keeps the csitJobId and the original kmJobId",len(again["jobs"])==1 and again["jobs"][0]["kmJobId"]==j["kmJobId"] and not bad(ia),bad(ia))

    # 3 sha mismatch
    b=new("tampered.txt",downloadFault="tamper",autoRun=True);ib=b["id"]
    check("3 altered bytes -> Failed, SHA256_MISMATCH, not retried",final(ib) and kms(ib)=="Failed" and doc(ib)["jobs"][-1]["error"]["code"]=="SHA256_MISMATCH"
          and doc(ib)["jobs"][-1]["error"]["retryable"] is False,doc(ib)["jobs"][-1].get("error"))
    check("3 only one download, no vectors",len(doc(ib)["jobs"][-1]["downloads"])==1 and ib not in km.q.ids())
    c=new("wrongsha.txt",wrongDeclaredSha=True,autoRun=True);ic=c["id"]
    check("3b wrong declared sha256 in the notice -> Failed SHA256_MISMATCH",final(ic) and doc(ic)["jobs"][-1]["error"]["code"]=="SHA256_MISMATCH",doc(ic)["jobs"][-1].get("error"))

    # 4 transient failure
    d=new("flaky.txt",downloadFault="unavailable",downloadFailures=2,autoRun=True);idd=d["id"]
    check("4 two 503s then Completed",final(idd) and kms(idd)=="Completed",kms(idd))
    check("4 no status regress",doc(idd)["jobs"][-1]["callbackStatuses"]==["Processing","Completed"],doc(idd)["jobs"][-1]["callbackStatuses"])
    check("4 three download attempts",len(doc(idd)["jobs"][-1]["downloads"])==3)

    # 5 bad token
    e=new("badtoken.txt",badToken=True,autoRun=True)
    check("5 wrong bearer rejected with 401",not bad(e["id"]) and doc(e["id"])["kmStatus"] is None,bad(e["id"]))

    # 6 CSIT outage while KM reports
    post("/api/callback-faults",{"callbackFailures":3,"callbackStatus":503})
    f=new("outage.txt",autoRun=True);iff=f["id"]
    check("6 callbacks survive a CSIT 503 outage",final(iff) and kms(iff)=="Completed",kms(iff))
    check("6 order kept after retries",doc(iff)["jobs"][-1]["callbackStatuses"]==["Processing","Completed"],doc(iff)["jobs"][-1]["callbackStatuses"])

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
    check("8 only the targeted file is gone",h1["id"] not in km.q.ids() and h2["id"] in km.q.ids())
    cl=(dd["result"] or {}).get("cleanup",{})
    check("8 cleanup: chunks Deleted, graphRelations NotPresent",cl.get("chunks")=="Deleted" and cl.get("graphRelations")=="NotPresent",cl)

    # 9 deletion idempotent; no resurrection
    again=post(f"/api/docs/{h1['id']}/delete",{"deletionRequestId":dd["deletionRequestId"]}).json()
    check("9 same deletionRequestId returns the same kmDeletionJobId",again["dels"][0]["kmDeletionJobId"]==dd["kmDeletionJobId"])
    late=post(f"/api/docs/{h1['id']}/dispatch").json()
    check("9 late upload notice for a deleted file is refused",late["jobs"][-1]["state"]=="Rejected",late["jobs"][-1]["timeline"][-1:])
    check("9 nothing was re-indexed",h1["id"] not in km.q.ids())

    rep=httpx.get(S+"/api/report").json()
    unexpected=[v for v in rep["violations"] if "unreachable" in v["what"]]
    check("overall: no KM spec violations recorded",not unexpected and not [v for v in rep["violations"] if "refused" not in v["what"] and "rejected" not in v["what"]],rep["violations"])
    km.close()
    with psycopg.connect(raw,autocommit=True) as cn:cn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(km.schema)))
    badr=[r for r in results if not r[1]]
    print(f"\n{len(results)-len(badr)}/{len(results)} checks passed")
    sys.exit(1 if badr else 0)

if __name__=="__main__":main()
