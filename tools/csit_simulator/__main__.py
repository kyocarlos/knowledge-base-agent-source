"""python -m tools.csit_simulator serve --km-base-url http://127.0.0.1:8000 --token dev-token --port 8765"""
import argparse,os
import uvicorn
from .sim import Sim,create_app

def main():
    p=argparse.ArgumentParser(description="CSIT x AI KM spec v1.3 simulator")
    p.add_argument("action",choices=["serve"])
    p.add_argument("--km-base-url",default=os.getenv("SIM_KM_BASE_URL","http://127.0.0.1:8000"),help="where KM accepts CSIT->KM calls")
    p.add_argument("--token",default=os.getenv("SIM_TOKEN","dev-csit-simulator-token"),help="bearer token both sides use (DEV only)")
    p.add_argument("--host",default="127.0.0.1");p.add_argument("--port",type=int,default=8765)
    a=p.parse_args()
    uvicorn.run(create_app(Sim(a.km_base_url,a.token)),host=a.host,port=a.port,log_level="warning")

if __name__=="__main__":main()
