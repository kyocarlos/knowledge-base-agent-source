#!/usr/bin/env python3
"""Validate the non-secret Phase 1 status manifest contract."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

SECRET_PATTERN = re.compile(r"(password|token|private.key|secret|bearer|BEGIN [A-Z ]+PRIVATE KEY)", re.I)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RELEASE_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
IMAGE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$")
REQUIRED_RELEASE_KEYS = (
    "application_commit",
    "operational_runner_commit",
    "release_id",
    "image_digest",
    "build_timestamp",
)


def validate_manifest(manifest: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if manifest.get("schema") != "km.phase1-status-manifest.v1":
        errors.append("unsupported schema")
    if manifest.get("phase") != "P1":
        errors.append("phase must be P1")
    release = manifest.get("approved_release")
    if not isinstance(release, dict):
        errors.append("approved_release must be an object")
    else:
        missing = [key for key in REQUIRED_RELEASE_KEYS if not release.get(key)]
        if missing:
            errors.append("approved_release missing: " + ", ".join(missing))
        else:
            for key in ("application_commit", "operational_runner_commit"):
                if not COMMIT_PATTERN.fullmatch(str(release[key])):
                    errors.append(f"{key} must be a 40-character lowercase commit")
            if not RELEASE_PATTERN.fullmatch(str(release["release_id"])):
                errors.append("release_id contains unsupported characters")
            if not IMAGE_PATTERN.fullmatch(str(release["image_digest"])):
                errors.append("image_digest must use sha256:<64 lowercase hex>")
            timestamp = str(release["build_timestamp"])
            if not TIMESTAMP_PATTERN.fullmatch(timestamp):
                errors.append("build_timestamp must be RFC3339 with timezone")
            else:
                try:
                    datetime.fromisoformat(timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp)
                except ValueError:
                    errors.append("build_timestamp is not a valid calendar timestamp")

    items = manifest.get("work_items")
    if not isinstance(items, list) or len(items) != 18:
        errors.append("work_items must contain exactly 18 P1 items")
        items = []
    ids = [item.get("wp_id") for item in items if isinstance(item, dict)]
    expected_ids = [f"P1-WP{i:02d}" for i in range(1, 19)]
    if ids != expected_ids:
        errors.append("work_items must use ordered P1-WP01..P1-WP18 IDs")
    allowed = set(manifest.get("statuses", []))
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"work_items[{index}] must be an object")
            continue
        for key in ("wp_id", "work_group", "name", "status", "km_ids"):
            if key not in item:
                errors.append(f"work_items[{index}] missing {key}")
        if item.get("status") not in allowed:
            errors.append(f"work_items[{index}] has unsupported status")
        if not isinstance(item.get("km_ids"), list):
            errors.append(f"work_items[{index}].km_ids must be a list")

    serialized = json.dumps(manifest, ensure_ascii=False)
    if SECRET_PATTERN.search(serialized):
        errors.append("manifest contains a secret-like field or value")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"manifest invalid: {exc}", file=sys.stderr)
        return 1
    errors = validate_manifest(manifest)
    if errors:
        for error in errors:
            print(f"FAIL_CLOSED: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"result": "PASS", "schema": manifest["schema"], "work_items": 18}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
