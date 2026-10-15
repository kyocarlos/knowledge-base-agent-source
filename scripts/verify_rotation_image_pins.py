"""Fail closed when a local Docker image reference no longer resolves to its approved ID."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    manifest = json.loads(Path(args.manifest).read_text())
    failures = []
    for item in manifest["images"]:
        name, reference, approved_id = item["name"], item["reference"], item["image_id"]
        result = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", reference],
            capture_output=True,
            text=True,
        )
        match = result.returncode == 0 and result.stdout.strip() == approved_id
        print(name, "PIN_PASS" if match else "PIN_FAIL")
        if not match:
            failures.append(name)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
