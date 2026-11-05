"""python -m tools.csit_simulator serve --km-base-url http://127.0.0.1:8000 --token dev-token --port 8765

Against a real KM deployment (which only trusts signed tokens over HTTPS), start it with --identity: the simulator then also serves
/.well-known/jwks and /oauth/token, signs its own calls to KM, verifies the tokens KM sends back, and serves HTTPS on --tls-port (certificate made
into --tls-dir; KM trusts tls-dir/ca.pem). Identity settings come from SIM_* environment variables (see IDENTITY_ENV below).
"""
import argparse,os,threading
from pathlib import Path
import uvicorn
from .sim import Sim
from .app import create_app

IDENTITY_ENV={"SIM_ISSUER":"token issuer, e.g. https://csit-sim:8443/ (KM's KM_CSIT_AUTHORITY)","SIM_KM_AUDIENCE":"audience of tokens sent to KM (KM_CSIT_AUDIENCE)",
              "SIM_OUTBOUND_AUDIENCE":"audience of tokens KM obtains (KM_CSIT_OUTBOUND_AUDIENCE)","SIM_KM_CLIENT_ID":"KM's client id (KM_CSIT_CLIENT_ID)",
              "SIM_KM_CLIENT_SECRET_FILE":"file holding KM's client secret","SIM_SERVICE_CLIENT_ID":"client id the simulator signs as (one of KM_CSIT_SERVICE_CLIENTS)",
              "SIM_TLS_NAMES":"comma separated DNS names for the certificate, e.g. csit-sim"}

def build_identity(data_dir):
    from .identity import Identity
    missing=[k for k in IDENTITY_ENV if k!="SIM_TLS_NAMES" and not os.getenv(k)]
    if missing:raise SystemExit("--identity needs: "+", ".join(missing))
    secret=Path(os.environ["SIM_KM_CLIENT_SECRET_FILE"]).read_text().strip()
    return Identity(os.environ["SIM_ISSUER"],os.environ["SIM_KM_AUDIENCE"],os.environ["SIM_OUTBOUND_AUDIENCE"],os.environ["SIM_KM_CLIENT_ID"],secret,
                    os.environ["SIM_SERVICE_CLIENT_ID"],data_dir=data_dir)

def main():
    p=argparse.ArgumentParser(description="CSIT x AI KM spec v1.3 / v1.4 simulator")
    p.add_argument("action",choices=["serve"])
    p.add_argument("--km-base-url",default=os.getenv("SIM_KM_BASE_URL","http://127.0.0.1:8000"),help="where KM accepts CSIT->KM calls")
    p.add_argument("--token",default=os.getenv("SIM_TOKEN","dev-csit-simulator-token"),help="bearer token both sides use (DEV only; ignored with --identity)")
    p.add_argument("--host",default="127.0.0.1");p.add_argument("--port",type=int,default=8765)
    p.add_argument("--data-dir",default=os.getenv("SIM_DATA_DIR"),help="keep documents, logs and the identity key across restarts")
    p.add_argument("--identity",action="store_true",help="act as the identity authority KM trusts (JWKS + token endpoint, signed tokens)")
    p.add_argument("--public-url",default=os.getenv("SIM_PUBLIC_URL",""),help="address KM reaches this simulator at, shown as document.downloadUrl in v2 notices")
    p.add_argument("--scope-style",choices=["v13","v14"],default=os.getenv("SIM_SCOPE_STYLE","v13"),help="scopes on tokens sent to KM: v1.3 km.ingestion.submit, or the v1.4 per-endpoint names")
    p.add_argument("--tls-port",type=int,default=0,help="also serve HTTPS on this port (needed when KM calls the simulator)")
    p.add_argument("--tls-dir",default=os.getenv("SIM_TLS_DIR"),help="where the generated CA and server certificate are kept")
    a=p.parse_args()
    identity=build_identity(a.data_dir) if a.identity else None
    app=create_app(Sim(a.km_base_url,a.token,data_dir=a.data_dir,identity=identity,public_base=a.public_url,scope_style=a.scope_style))
    if a.tls_port:
        from .tls import ensure
        names=[n.strip() for n in os.getenv("SIM_TLS_NAMES","localhost").split(",") if n.strip()]
        files=ensure(a.tls_dir or (Path(a.data_dir or ".")/"tls"),names)
        https=uvicorn.Server(uvicorn.Config(app,host=a.host,port=a.tls_port,ssl_certfile=str(files["server.pem"]),ssl_keyfile=str(files["server.key"]),log_level="warning"))
        threading.Thread(target=https.run,daemon=True).start()
        print(f"  HTTPS {a.host}:{a.tls_port}  CA: {files['ca.pem']}",flush=True)
    print(f"  HTTP  {a.host}:{a.port}  identity={'on' if identity else 'off'}",flush=True)
    uvicorn.run(app,host=a.host,port=a.port,log_level="warning")

if __name__=="__main__":main()
