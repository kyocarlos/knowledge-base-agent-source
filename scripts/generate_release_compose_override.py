#!/usr/bin/env python3
"""Generate a YAML-safe exact-release Compose override.

All release metadata is serialized as strings and validated again after YAML
round-trip. This file contains no credentials and is intended for an isolated
or explicitly approved deployment procedure.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.core.release_metadata import validate_release_identity

SERVICES = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")


def build_override(metadata: dict[str, str], image: str) -> dict:
    services = {}
    for name in SERVICES:
        services[name] = {
            "image": str(image),
            "pull_policy": "never",
            "environment": {
                **{key: str(value) for key, value in metadata.items()},
                "KB_JOB_LEDGER_PATH": "/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3",
            },
        }
    return {"services": services}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--build-timestamp", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    metadata = validate_release_identity(
        source_commit=args.commit,
        release_id=args.release_id,
        image_digest=args.image_digest,
        build_timestamp=args.build_timestamp,
    )
    document = build_override(metadata, str(args.image))
    rendered = yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    reparsed = yaml.safe_load(rendered)
    for service in SERVICES:
        observed = reparsed["services"][service]["environment"]
        if any(observed[key] != value for key, value in metadata.items()):
            raise RuntimeError(f"YAML round-trip changed release metadata for {service}")
        if not isinstance(observed["KM_BUILD_TIMESTAMP"], str):
            raise RuntimeError(f"YAML round-trip changed timestamp type for {service}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "services": list(SERVICES), "result": "PASS"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
