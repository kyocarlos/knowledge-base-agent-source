#!/usr/bin/env python3
"""Fail-closed, read-only validation of shared Job Lease ledger mounts."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def docker_inspect(name: str) -> dict:
    return json.loads(subprocess.check_output(["docker", "inspect", name], text=True))[0]


def _ledger_source(container: dict, logical_path: str) -> Path:
    logical = Path(logical_path)
    matches = []
    for mount in container.get("Mounts", []):
        destination = Path(mount["Destination"])
        try:
            relative = logical.relative_to(destination)
        except ValueError:
            continue
        matches.append((len(destination.parts), Path(mount["Source"]) / relative))
    if not matches:
        raise ValueError(f"{container.get('Name', '<unknown>')}: no mount covers {logical_path}")
    return max(matches, key=lambda item: item[0])[1]


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate(containers: list[str], logical_path: str) -> dict:
    records = []
    for name in containers:
        container = docker_inspect(name)
        env = dict(
            item.split("=", 1)
            for item in container.get("Config", {}).get("Env", [])
            if "=" in item
        )
        effective = env.get("KB_JOB_LEDGER_PATH")
        if effective != logical_path:
            raise ValueError(f"{name}: effective KB_JOB_LEDGER_PATH={effective!r}, expected {logical_path!r}")
        source = _ledger_source(container, logical_path)
        stat = source.stat() if source.exists() else None
        records.append(
            {
                "container": name,
                "logical_path": effective,
                "host_source": str(source),
                "device_inode": f"{stat.st_dev}:{stat.st_ino}" if stat else None,
                "sha256": _sha256(source),
                "exists": stat is not None,
            }
        )
    identities = {(row["host_source"], row["device_inode"], row["sha256"]) for row in records}
    return {
        "result": "PASS" if len(identities) == 1 else "FAIL",
        "logical_path": logical_path,
        "records": records,
        "physical_identity_count": len(identities),
        "read_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logical-path", required=True)
    parser.add_argument("--container", action="append", required=True)
    args = parser.parse_args()
    try:
        result = validate(args.container, args.logical_path)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"result": "FAIL", "reason": str(exc), "read_only": True}, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
