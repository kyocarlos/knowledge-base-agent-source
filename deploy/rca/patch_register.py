"""Add the flag-gated RCA router registration to the web app already in the image, without replacing the file (the image's version stays authoritative)."""
import sys,re
path=sys.argv[1]
src=open(path,encoding="utf-8").read()
MARK="# --- RCA report comparison (flag-gated) ---"
if MARK in src:
    print("already patched");sys.exit(0)
BLOCK=MARK+'''
import os as _rca_os
if _rca_os.getenv("KM_RCA_ENABLED") == "1":  # a failure here must never stop the app
    try:
        from .rca_routes import create_router as _create_rca_router
        app.include_router(_create_rca_router())
    except Exception:  # noqa: BLE001
        import logging as _rca_logging
        _rca_logging.getLogger("km.rca").exception("RCA routes were not registered")
'''
# insert after the last top-level app.include_router(...) line, which is always after `app` exists
lines=src.split("\n")
idx=[i for i,l in enumerate(lines) if re.match(r"^app\.include_router\(",l)]
if not idx:
    sys.exit("no app.include_router anchor found; refusing to patch")
i=idx[-1]
lines.insert(i+1,BLOCK.rstrip("\n"))
open(path,"w",encoding="utf-8").write("\n".join(lines))
print("patched after line",i+1)
