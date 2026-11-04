"""Register the RCA Celery task by importing it at the end of the worker's tasks module already in the image (the image's file stays authoritative)."""
import sys
path=sys.argv[1]
src=open(path,encoding="utf-8").read()
MARK="# --- RCA analysis task (registers tasks.rca_analyze_task) ---"
if MARK in src:
    print("already patched");sys.exit(0)
if "celery_app = Celery(" not in src and "celery_app=Celery(" not in src:
    sys.exit("celery_app not found in tasks.py; refusing to patch")
src=src.rstrip("\n")+"\n\n"+MARK+'''
try:
    from . import rca_tasks  # noqa: F401
except Exception:  # noqa: BLE001 - the worker must keep serving its other tasks
    import logging as _rca_logging
    _rca_logging.getLogger("km.rca").exception("RCA task was not registered")
'''
open(path,"w",encoding="utf-8").write(src)
print("patched")
