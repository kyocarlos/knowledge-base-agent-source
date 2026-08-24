#!/usr/bin/env python3
"""Validate the persistent frontend directory before compose/restart."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

REQUIRED = ("index.html", "chat.html")

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def validate(source: Path, *, allow_temporary: bool = False) -> dict[str, object]:
    source = source.expanduser().resolve()
    if str(source).startswith("/tmp/") and not allow_temporary:
        raise ValueError(f"frontend runtime must not use temporary path: {source}")
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"frontend mount source is not a persistent directory: {source}")
    files = sorted(path for path in source.rglob("*") if path.is_file())
    missing = [name for name in REQUIRED if not (source / name).is_file()]
    unreadable = [str(path.relative_to(source)) for path in files if not os.access(path, os.R_OK)]
    if missing:
        raise ValueError(f"required frontend files missing: {', '.join(missing)}")
    if not files:
        raise ValueError("frontend static directory is empty")
    if unreadable:
        raise ValueError(f"frontend files are unreadable: {', '.join(unreadable)}")
    return {
        "source": str(source),
        "file_count": len(files),
        "asset_count": sum(path.suffix.lower() in {".js", ".css", ".map"} for path in files),
        "required_files": list(REQUIRED),
        "manifest": {str(path.relative_to(source)): sha256(path) for path in files},
        "mode": oct(source.stat().st_mode & 0o777),
        "owner_uid": source.stat().st_uid,
        "owner_gid": source.stat().st_gid,
        "result": "PASS",
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument(
        "--allow-temporary",
        action="store_true",
        help="allow /tmp paths for disposable isolated validation only",
    )
    args = parser.parse_args()
    evidence = validate(args.source_dir, allow_temporary=args.allow_temporary)
    if args.manifest_output:
        args.manifest_output.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        os.chmod(args.manifest_output, 0o600)
    print(json.dumps(evidence, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
