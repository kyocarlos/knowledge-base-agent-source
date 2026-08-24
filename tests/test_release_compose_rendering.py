from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts/validate_release_compose_metadata.py"
COMMIT = "a" * 40
RELEASE = "wp1-metadata-fix-20260824-r1"
DIGEST = "sha256:" + "b" * 64
TIMESTAMP = "2026-08-24T06:47:20+08:00"
SERVICES = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")


def render_compose(path: Path, env: dict[str, str]) -> str:
    if shutil.which("docker") is None:
        pytest.skip("docker compose is not available")
    result = subprocess.run(
        ["docker", "compose", "-f", str(path), "config", "--format", "json"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def validate_rendered(rendered: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--commit",
            COMMIT,
            "--release-id",
            RELEASE,
            "--image-digest",
            DIGEST,
            "--build-timestamp",
            TIMESTAMP,
        ],
        input=rendered,
        capture_output=True,
        text=True,
    )


def test_unquoted_yaml_timestamp_coercion_is_caught(tmp_path: Path) -> None:
    service_blocks = "\n".join(
        f"  {name}:\n    image: alpine\n    environment:\n"
        f"      KM_GIT_COMMIT: {COMMIT}\n"
        f"      KM_RELEASE_ID: {RELEASE}\n"
        f"      KM_IMAGE_DIGEST: {DIGEST}\n"
        f"      KM_BUILD_TIMESTAMP: {TIMESTAMP}"
        for name in SERVICES
    )
    compose = tmp_path / "coerced.yml"
    compose.write_text(f"services:\n{service_blocks}\n", encoding="utf-8")
    rendered = render_compose(compose, {})
    observed = json.loads(rendered)["services"]["web"]["environment"]["KM_BUILD_TIMESTAMP"]
    assert observed != TIMESTAMP
    assert validate_rendered(rendered).returncode != 0


def test_list_environment_preserves_rfc3339_timestamp(tmp_path: Path) -> None:
    metadata = {
        "KM_GIT_COMMIT": COMMIT,
        "KM_RELEASE_ID": RELEASE,
        "KM_IMAGE_DIGEST": DIGEST,
        "KM_BUILD_TIMESTAMP": TIMESTAMP,
    }
    service_blocks = "\n".join(
        f"  {name}:\n    image: alpine\n    environment:\n"
        + "\n".join(f"      - {key}=${{{key}}}" for key in metadata)
        for name in SERVICES
    )
    compose = tmp_path / "preserved.yml"
    compose.write_text(f"services:\n{service_blocks}\n", encoding="utf-8")
    rendered = render_compose(compose, metadata)
    result = validate_rendered(rendered)
    assert result.returncode == 0, result.stderr
