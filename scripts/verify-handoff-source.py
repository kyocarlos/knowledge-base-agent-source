#!/usr/bin/env python3
"""Verify the delivered source/build/test files without reading secrets or runtime state."""
import hashlib,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/"docs/handoff/source-manifest.json").read_text())
errors=[]
for entry in manifest["files"]:
    path=(root/entry["path"]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        errors.append(entry["path"])
        continue
    if hashlib.sha256(path.read_bytes()).hexdigest()!=entry["sha256"]:
        errors.append(entry["path"])
if errors:
    print("SOURCE MANIFEST FAIL:",", ".join(errors))
    sys.exit(1)
print(f"SOURCE MANIFEST PASS: {len(manifest['files'])} files")
