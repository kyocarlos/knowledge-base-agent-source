"""One command to try the whole flow locally: PostgreSQL + real KM (routes + worker) + this simulator's UI.

    python -m tools.csit_simulator.demo                 # embedded PostgreSQL (pip install pgserver)
    python -m tools.csit_simulator.demo --database-url postgresql://user:pw@host/db
"""
import argparse,shutil,sys,time,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from tools.csit_simulator.km_local import LocalKm,serve
from tools.csit_simulator.sim import Sim
from tools.csit_simulator.app import create_app

def main():
    for stream in (sys.stdout,sys.stderr):
        try:stream.reconfigure(encoding="utf-8",errors="replace")
        except Exception:pass
    p=argparse.ArgumentParser(description="CSIT simulator + local KM")
    p.add_argument("--database-url");p.add_argument("--sim-port",type=int,default=8765);p.add_argument("--km-port",type=int,default=8000)
    p.add_argument("--token",default="dev-csit-simulator-token");p.add_argument("--llm",action="store_true",help="use the KM primary LLM instead of the rule-based stub")
    p.add_argument("--no-browser",action="store_true");p.add_argument("--data-dir",default=str(Path(__file__).parent/".demo"))
    a=p.parse_args()
    url=a.database_url
    if not url:
        try:import pgserver
        except ImportError:sys.exit("pip install pgserver  (or pass --database-url)")
        (Path(a.data_dir)).mkdir(parents=True,exist_ok=True)
        pg=pgserver.get_server(str(Path(a.data_dir)/"pg"),cleanup_mode=None);url=pg.get_uri()
    # Every run starts clean: the KM schema is dropped and the simulator's documents removed (vectors are in memory anyway).
    import psycopg
    from psycopg import sql
    with psycopg.connect(url,autocommit=True) as c:c.execute("DROP SCHEMA IF EXISTS csit_demo CASCADE")
    shutil.rmtree(Path(a.data_dir)/"csit",ignore_errors=True)
    sim_url=f"http://127.0.0.1:{a.sim_port}"
    semantic="stub"
    if a.llm:
        from src.csit_integration_v1.doclib_metadata import make_semantic_extractor
        from src.csit_integration_v1.doclib_llm import complete
        semantic=make_semantic_extractor(complete)
    km=LocalKm(url,sim_url,a.token,a.km_port,semantic=semantic,schema="csit_demo")
    sim=Sim(f"http://127.0.0.1:{a.km_port}",a.token,data_dir=str(Path(a.data_dir)/"csit"),inspect=km.inspect)
    serve(create_app(sim),a.sim_port)
    print(f"\n  CSIT 模擬器  {sim_url}\n  KM (本機)    http://127.0.0.1:{a.km_port}   (向量庫為記憶體版,重啟後清空)\n  Ctrl+C 結束\n",flush=True)
    if not a.no_browser:webbrowser.open(sim_url)
    try:
        while True:time.sleep(3600)
    except KeyboardInterrupt:km.close()

if __name__=="__main__":main()
