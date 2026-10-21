#!/usr/bin/env python3
"""Verify vendored schemas byte-for-byte against their pinned CSIT commit."""
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PIN=ROOT/"contracts/csit-km-integration-v1/UPSTREAM.json"
EXPECTED_COMMIT="3a9ae52f04625aeee5fd01e7a3565f5972fc9122"
REQUIRED={"ingestion-request.schema.json","callback-processing.schema.json","callback-completed.schema.json","callback-failed.schema.json"}
pin=json.loads(PIN.read_text())
if pin.get("repository")!="https://github.com/pattymou/CSIT-System.git" or pin.get("commit")!=EXPECTED_COMMIT or pin.get("path")!="contracts/csit-km-integration-v1":
    raise SystemExit("canonical upstream pin mismatch")
if set(pin.get("schemas",{}))!=REQUIRED:
    raise SystemExit("canonical schema pin must list exactly the four v1 schemas")
base=f"https://raw.githubusercontent.com/pattymou/CSIT-System/{EXPECTED_COMMIT}/{pin['path']}"
local=ROOT/pin["path"]
with tempfile.TemporaryDirectory(prefix="km-csit-contract-") as td:
    for name in sorted(REQUIRED):
        target=Path(td)/name
        subprocess.run(["curl","--fail","--silent","--show-error","--location","--max-time","45",f"{base}/{name}","--output",str(target)],check=True)
        upstream=target.read_bytes(); vendored=(local/name).read_bytes()
        upstream_hash=hashlib.sha256(upstream).hexdigest(); vendored_hash=hashlib.sha256(vendored).hexdigest()
        if upstream_hash!=pin["schemas"][name] or vendored_hash!=upstream_hash or vendored!=upstream:
            raise SystemExit(f"canonical contract drift: {name} (upstream={upstream_hash}, vendored={vendored_hash})")
        print(f"PASS {name} sha256={vendored_hash}")
print(f"PASS pinned CSIT commit {EXPECTED_COMMIT}")
