from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/generate_release_compose_override.py"
COMMIT = "a" * 40
RELEASE = "wp1-deployment-metadata-yaml-quoting-fix"
DIGEST = "sha256:" + "b" * 64
SERVICES = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")


def test_rfc3339_values_survive_yaml_and_compose_round_trip(tmp_path: Path) -> None:
    for timestamp in ("2026-08-26T13:58:10+08:00", "2026-08-26T05:58:10Z", "2026-08-26T01:58:10-04:00"):
        output = tmp_path / f"override-{timestamp[-6:].replace(':', '')}.yml"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--image", "candidate:exact", "--commit", COMMIT,
             "--release-id", RELEASE, "--image-digest", DIGEST, "--build-timestamp", timestamp,
             "--output", str(output)],
            check=True, capture_output=True, text=True,
        )
        assert json.loads(result.stdout)["result"] == "PASS"
        document = yaml.safe_load(output.read_text(encoding="utf-8"))
        for service in SERVICES:
            environment = document["services"][service]["environment"]
            assert environment["KM_BUILD_TIMESTAMP"] == timestamp
            assert isinstance(environment["KM_BUILD_TIMESTAMP"], str)
            assert environment["KM_GIT_COMMIT"] == COMMIT
            assert environment["KB_JOB_LEDGER_PATH"].endswith("job-ledger.sqlite3")

        base = tmp_path / "base.yml"
        base.write_text("services:\n  web:\n    image: candidate:exact\n", encoding="utf-8")
        compose = subprocess.run(
            ["docker", "compose", "-f", str(base), "-f", str(output), "config", "--format", "json"],
            check=False, capture_output=True, text=True,
        )
        if compose.returncode != 0:
            if "not found" in (compose.stderr or "").lower() or "cannot connect" in (compose.stderr or "").lower():
                continue
            raise AssertionError(compose.stderr)
        rendered = json.loads(compose.stdout)
        for service in SERVICES:
            values = rendered["services"][service]["environment"]
            assert rendered["services"][service]["image"] == "candidate:exact"
            assert values["KM_BUILD_TIMESTAMP"] == timestamp
            assert isinstance(values["KM_BUILD_TIMESTAMP"], str)
            assert values["KM_GIT_COMMIT"] == COMMIT
            assert values["KB_JOB_LEDGER_PATH"] == "/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3"


def test_invalid_timestamp_is_rejected(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--image", "candidate:exact", "--commit", COMMIT,
         "--release-id", RELEASE, "--image-digest", DIGEST, "--build-timestamp", "2026-08-26 13:58:10 CST",
         "--output", str(tmp_path / "invalid.yml")],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
