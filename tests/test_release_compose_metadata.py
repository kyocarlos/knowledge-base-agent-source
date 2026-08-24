from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate_release_compose_metadata.py"
COMMIT = "a" * 40
RELEASE = "wp1-metadata-fix-20260824-r1"
DIGEST = "sha256:" + "b" * 64
TIMESTAMP = "2026-08-24T06:47:20+08:00"
SERVICES = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")


def run_validator(timestamp: str) -> subprocess.CompletedProcess[str]:
    metadata = {
        "KM_GIT_COMMIT": COMMIT,
        "KM_RELEASE_ID": RELEASE,
        "KM_IMAGE_DIGEST": DIGEST,
        "KM_BUILD_TIMESTAMP": timestamp,
    }
    rendered = {"services": {name: {"environment": metadata} for name in SERVICES}}
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--commit",
            COMMIT,
            "--release-id",
            RELEASE,
            "--image-digest",
            DIGEST,
            "--build-timestamp",
            TIMESTAMP,
        ],
        input=json.dumps(rendered),
        capture_output=True,
        text=True,
    )


def test_rendered_compose_metadata_is_identical_for_four_services() -> None:
    result = run_validator(TIMESTAMP)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["result"] == "PASS"


def test_yaml_timestamp_coercion_is_rejected_before_deployment() -> None:
    result = run_validator("2026-08-24 06:47:20 +0800 CST")
    assert result.returncode != 0
    assert "KM_BUILD_TIMESTAMP" in result.stderr
