#!/usr/bin/env python3
"""Fail-closed runtime capability gate for an immutable candidate image."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


PROBE = r'''
from app.core.config import AppSettings
from app.core.release_metadata import validate_release_identity
from src.test_reports.auth import authenticate_e2e_agent, authenticate_e2e_cleanup, authenticate_e2e_reviewer, authenticate_report_agent, authenticate_report_reviewer
from src.web_api import report_routes

assert callable(authenticate_report_agent)
assert callable(authenticate_report_reviewer)
assert callable(authenticate_e2e_agent)
assert callable(authenticate_e2e_reviewer)
assert callable(authenticate_e2e_cleanup)
assert hasattr(report_routes, "upload_report")
assert hasattr(report_routes, "approve_report_submission")
settings = AppSettings.from_env()
expected = validate_release_identity(
    source_commit=settings.commit or "",
    release_id=settings.release_id or "",
    image_digest=settings.image_digest or "",
    build_timestamp=settings.build_timestamp or "",
)
print({"auth_routing": "present", "report_routes": "present", "metadata": expected})
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--build-timestamp", required=True)
    args = parser.parse_args()
    env = [
        "-e", f"KM_GIT_COMMIT={args.commit}",
        "-e", f"KM_RELEASE_ID={args.release_id}",
        "-e", f"KM_IMAGE_DIGEST={args.image_digest}",
        "-e", f"KM_BUILD_TIMESTAMP={args.build_timestamp}",
    ]
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "python", *env, args.image, "-c", PROBE],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        print("release image capability gate: FAIL", file=sys.stderr)
        print(result.stderr[-4000:], file=sys.stderr)
        return result.returncode
    print(json.dumps({"schema": "km.release-image-capabilities.v1", "result": "PASS", "image": args.image, "probe": result.stdout.strip()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
