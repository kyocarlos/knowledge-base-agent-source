"""Local RCA demo: synthetic km_test data + the real RCA routes + the real page, with a rule-based stand-in for the model.

    python -m tools.rca_demo                      # embedded PostgreSQL (pip install pgserver)
    python -m tools.rca_demo --database-url postgresql://user:pw@host/db

Nothing here touches a KM deployment. The 'model' only rephrases the evidence pack, so it demonstrates the page and the checks, not AI quality.
"""
import argparse,json,random,sys,threading,time,uuid,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
import psycopg,uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from src.report_numeric import timescale
from src.web_api.rca_routes import create_router
from src.report_numeric import rca_service,compare

ROLES=["CSIT_ENGINEER"]
PAGE=ROOT/"frontend"/"zones"/"csit"/"rca.html"

def seed(conn):
    conn.execute("DROP SCHEMA IF EXISTS km_test CASCADE");conn.execute(timescale.ddl())
    for m in timescale.load_dictionary():
        conn.execute("INSERT INTO km_test.metric_dictionary(metric_name,unit,kind,description) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",(m["metric_name"],m["unit"],m["kind"],m.get("description")))
    def run(rid,model,*,fw,hw,date,rtype="wifi_throughput",eth="1G",quality="clean",overall="pass",chip="Qualcomm"):
        conn.execute("""INSERT INTO km_test.test_run(test_run_id,id_basis,report_id,document_id,document_version,report_type,technology,product_id,product_id_basis,dut_model,npi_stage,
          firmware_version,hardware_version,chipset_vendor,ethernet_type,test_date,overall_result,source_system,approval_status,approval_basis,publish_status,visibility,access_roles,
          access_departments,quality_status,formula_error_count,package_id,schema_version,content_hash) VALUES(%s,'derived',%s,%s,'1',%s,'WiFi7',%s,'derived',%s,'EVT',%s,%s,%s,%s,%s,%s,
          'ManualUpload','approved','assumed_manual','published','internal',%s,%s,%s,%s,%s,'1',%s)""",(rid,rid,"DOC-"+rid,rtype,model,model,fw,hw,chip,eth,date,overall,ROLES,["CSIT"],quality,0 if quality=="clean" else 3,"pkg-"+rid,rid))
    def m(rid,case,metric,unit,val,band,bw,ch,direction,cell,att=None):
        conn.execute("""INSERT INTO km_test.test_measurement(measurement_id,test_run_id,test_case_id,metric_name,value,unit,value_basis,band,bandwidth_mhz,channel,direction,attenuation_db,source_sheet,source_cell_range)
          VALUES(%s,%s,%s,%s,%s,%s,'measured',%s,%s,%s,%s,%s,'Throughput',%s)""",(uuid.uuid4(),rid,case,metric,round(val,1),unit,band,bw,ch,direction,att,cell))
    P="RTF7907VW-D223"
    run("RTF7907-FW100",P,fw="1.0.0",hw="A",date="2026-10-01")
    run("RTF7907-FW110",P,fw="1.1.0",hw="A",date="2026-10-20",overall="fail")
    run("RTF7907-FW110-HWB",P,fw="1.1.0",hw="B",date="2026-11-01",eth="2.5G",quality="source_errors_accepted",overall="fail")
    run("NCQ2200-FW200","NCQ2200B2V-D294",fw="2.0.0",hw="A",date="2026-10-15",chip="MediaTek")
    run("RTF7907-RVR-FW100",P,fw="1.0.0",hw="A",date="2026-10-02",rtype="wifi_rvr")
    rnd=random.Random(7)
    plan=[("5GHz",80,[36,40,44,48],"Throughput",0),("5GHz",160,[36,44],"Throughput",0),("2.4GHz",20,[1,6,11],"Throughput",0)]
    for rid,tag in (("RTF7907-FW100","a"),("RTF7907-FW110","b"),("RTF7907-FW110-HWB","c"),("NCQ2200-FW200","n")):
        row=2
        for band,bw,chs,_,_ in plan:
            base={80:900,160:1700,20:110}[bw]
            for ch in chs:
                for direction in ("dl","ul"):
                    v=base*(0.97+rnd.random()*0.06)*(0.93 if direction=="ul" else 1)
                    if tag in "bc":
                        v*=1+rnd.uniform(-0.015,0.015)
                        if band=="5GHz" and bw==80 and ch==36 and direction=="dl":v*=0.72        # the regression to find
                        if band=="5GHz" and bw==160 and direction=="ul":v*=0.88
                    if tag=="c" and band=="5GHz" and bw==80 and ch==48 and direction=="dl":continue   # not measured in the newest report
                    m(rid,"Throughput","throughput","Mbps",v,band,bw,ch,direction,f"B{row}");row+=1
        m(rid,"Throughput","rssi","dBm",-55 if tag=="a" else -63 if tag in "bc" else -57,"5GHz",80,36,"dl",f"E{row}")
    for rid,res in (("RTF7907-FW100","pass"),("RTF7907-FW110","fail"),("RTF7907-FW110-HWB","fail")):
        conn.execute("INSERT INTO km_test.test_item_result(result_id,test_run_id,test_case_id,item_label,result,result_basis,source_sheet,source_cell_range) VALUES(%s,%s,'Throughput','5GHz 80MHz ch36 DL',%s,'report','Summary','C4')",(uuid.uuid4(),rid,res))
        conn.execute("INSERT INTO km_test.test_item_result(result_id,test_run_id,test_case_id,item_label,result,result_basis,source_sheet,source_cell_range) VALUES(%s,%s,'Throughput','2.4GHz 20MHz ch6 DL','pass','report','Summary','C9')",(uuid.uuid4(),rid))
        conn.execute("INSERT INTO km_test.test_condition(condition_id,test_run_id,name,value,source_sheet,source_cell_range) VALUES(%s,%s,'best_angle',%s,'Setup','B7')",(uuid.uuid4(),rid,90 if rid.endswith("FW100") else 120))
        conn.execute("INSERT INTO km_test.criteria_reference(criteria_id,test_run_id,band,bandwidth_mhz,reference_rate_mbps,criteria_value,criteria_unit,source_sheet,source_cell_range) VALUES(%s,%s,'5GHz',80,1000,%s,'Mbps','Criteria','B3')",(uuid.uuid4(),rid,800 if rid.endswith("FW100") or rid.endswith("FW110") else 850))

def stub_llm(messages):
    """Rephrases the evidence pack in the required JSON shape. It cannot reason about causes; it exists to exercise the page and the checks."""
    pack=json.loads(messages[1]["content"].split("證據包：\n",1)[1])
    fac={f["factor"]:f for f in pack["factors"]}
    top=pack["diffs"][:3]
    obs=[{"text":f"{d['label']}：基準 {d['per_run'][0]['value']} {d['unit']}，另一份為 {d['per_run'][1]['value']} {d['unit']}。","evidence":[d["id"]]} for d in top]
    for key,name in (("firmware_version","韌體版本"),("hardware_version","硬體版本"),("ethernet_type","乙太網路類型")):
        if key in fac:obs.append({"text":f"{name}不同：{' → '.join(str(v) for v in fac[key]['values'])}。","evidence":[fac[key]["id"]]})
    hyps=[]
    for key,name,mech in (("firmware_version","韌體版本","韌體改動可能影響特定頻寬與通道的資料路徑，只在部分條件出現下降符合這個樣子"),
                          ("hardware_version","硬體版本","硬體版本不同可能改變射頻或散熱條件"),
                          ("ethernet_type","乙太網路類型","有線端速率不同可能限制測試上限")):
        if key in fac and top:
            hyps.append({"cause":f"{name}變動造成特定條件的量測差異","mechanism":mech,"supports":[fac[key]["id"],top[0]["id"]],"against":[],
                         "missing_evidence":[f"{name}對應的釋出說明或變更紀錄","同一條件的重複量測以排除量測變異"],"confidence":"medium" if not pack["confounded"] else "low",
                         "verify_steps":[f"只改變{name}、其餘條件不變，重測相同條件","確認基準與比較報告的量測環境（角度、有線端速率）一致"]})
    gaps=["只有 " + str(len(pack["runs"])) + " 份報告，無法排除量測環境造成的差異"]
    if pack["confounded"]:gaps.append("韌體、硬體、乙太網路類型同時變動，需要拆開變因、只換一個再重測")
    if pack["quality"]:gaps.append("有報告的來源檔含公式錯誤儲存格，資料品質需先確認")
    unexplained=[{"text":f"{d['label']} 的變化沒有直接對應的變因。","evidence":[d["id"]]} for d in top[1:2]]
    return json.dumps({"summary":f"{len(pack['diffs'])} 筆顯著差異，最大的是 {top[0]['label']}。" if top else "沒有顯著差異。","observations":obs[:6] or [{"text":"沒有顯著差異。","evidence":[pack['factors'][0]['id']] if pack['factors'] else []}],
                       "hypotheses":hyps,"unexplained":unexplained,"data_gaps":gaps},ensure_ascii=False)

class ThreadTasks:
    """Stands in for the Celery worker: runs the analysis in a thread after a short delay so the page's polling can be seen."""
    def __init__(self,connect,roles,llm,delay=4):self.connect,self.roles,self.llm,self.delay,self.done,self.n=connect,roles,llm,delay,{},0
    def submit(self,run_ids,question,owner):
        self.n+=1;tid="demo-%d"%self.n
        def work():
            time.sleep(self.delay)
            try:self.done[tid]={"owner":owner,"status":"done",**rca_service.analyze(self.connect,self.roles,self.llm,run_ids,question)}
            except compare.CompareError as e:self.done[tid]={"owner":owner,"status":"failed","detail":str(e)}
        threading.Thread(target=work,daemon=True).start();return tid
    def fetch(self,tid):return self.done.get(tid)

def main():
    p=argparse.ArgumentParser();p.add_argument("--database-url");p.add_argument("--port",type=int,default=8770);p.add_argument("--no-browser",action="store_true");p.add_argument("--keep-data",action="store_true",help="do not reseed: use the km_test data already in the database (e.g. real imported reports)")
    a=p.parse_args()
    for s in (sys.stdout,sys.stderr):
        try:s.reconfigure(encoding="utf-8",errors="replace")
        except Exception:pass
    url=a.database_url
    if not url:
        try:import pgserver
        except ImportError:sys.exit("pip install pgserver  (or pass --database-url)")
        d=Path(__file__).parent/".demo";d.mkdir(exist_ok=True);url=pgserver.get_server(str(d/"pg"),cleanup_mode=None).get_uri()
    if not a.keep_data:
        with psycopg.connect(url,autocommit=True) as c:seed(c)
    app=FastAPI()
    @app.middleware("http")
    async def ident(request,call_next):
        request.state.km_identity={"sub":"demo","instance_id":"csit"};return await call_next(request)
    connect=lambda:psycopg.connect(url,autocommit=True)
    app.include_router(create_router(connect=connect,tasks=ThreadTasks(connect,ROLES,stub_llm),roles=lambda:ROLES))
    @app.get("/api/rca/v1/demo-info")
    def info():return {"demo":True}
    @app.get("/")
    def page():return FileResponse(PAGE)
    # the zone style sheets, icons and the other zone pages, so the page is judged next to the real ones
    app.mount("/",StaticFiles(directory=str(ROOT/"frontend")),name="frontend")
    print(f"\n  RCA 示範  http://127.0.0.1:{a.port}/   (合成資料;分析為規則產生的替身)\n  Ctrl+C 結束\n",flush=True)
    if not a.no_browser:webbrowser.open(f"http://127.0.0.1:{a.port}/")
    uvicorn.run(app,host="127.0.0.1",port=a.port,log_level="warning")

if __name__=="__main__":main()
