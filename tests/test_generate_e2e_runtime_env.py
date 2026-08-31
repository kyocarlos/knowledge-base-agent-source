from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/generate_e2e_runtime_env.py"
ROLES = ("e2e-agent-01", "e2e-reviewer-01", "e2e-cleanup-01")


def hash_file(path: Path) -> None:
    path.write_text(json.dumps({role: {"token_sha256": "a" * 64} for role in ROLES}) + "\n", encoding="utf-8")
    path.chmod(0o600)


def run_generator(hash_path: Path, output: Path, mode: str, run_id: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--hash-file", str(hash_path), "--output", str(output),
         "--execution-mode", mode, "--run-id-prefix", run_id],
        capture_output=True,
        text=True,
    )


def test_isolated_overlay_is_protected_and_contains_only_expected_contract(tmp_path):
    hashes = tmp_path / "hashes.json"
    output = tmp_path / "isolated" / "e2e.env"
    hash_file(hashes)
    result = run_generator(hashes, output, "isolated", "TR-E2E-WP1-GATEB-ISOLATED-test")
    assert result.returncode == 0, result.stderr
    assert output.stat().st_mode & 0o777 == 0o600
    content = output.read_text(encoding="utf-8")
    assert "KB_E2E_WRITE_MODE_ENABLED=true" in content
    assert "KB_E2E_CLEANUP_ENABLED=true" in content
    assert "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX=" in content
    assert all(key in content for key in ("KB_E2E_AGENT_TOKEN_HASHES_JSON", "KB_E2E_REVIEWER_TOKEN_HASHES_JSON", "KB_E2E_CLEANUP_TOKEN_HASHES_JSON"))
    assert "a" * 64 in content
    assert "secrets_included" not in content


def test_production_and_isolated_run_id_contracts_are_explicit(tmp_path):
    hashes = tmp_path / "hashes.json"
    hash_file(hashes)
    production = run_generator(hashes, tmp_path / "prod.env", "production", "TR-E2E-WP1-PROD-test")
    assert production.returncode == 0
    assert run_generator(hashes, tmp_path / "bad.env", "production", "TR-E2E-WP1-GATEB-ISOLATED-test").returncode != 0
    assert run_generator(hashes, tmp_path / "bad2.env", "isolated", "TR-E2E-WP1-PROD-test").returncode != 0


def test_isolated_overlay_rejects_production_namespace(tmp_path):
    hashes = tmp_path / "hashes.json"
    hash_file(hashes)
    output = tmp_path / "production-acceptance" / "e2e.env"
    result = run_generator(hashes, output, "isolated", "TR-E2E-WP1-GATEB-ISOLATED-test")
    assert result.returncode != 0
    assert not output.exists()


def test_reused_output_and_malformed_mapping_fail_closed(tmp_path):
    hashes = tmp_path / "hashes.json"
    output = tmp_path / "e2e.env"
    hash_file(hashes)
    assert run_generator(hashes, output, "isolated", "TR-E2E-WP1-GATEB-ISOLATED-test").returncode == 0
    assert run_generator(hashes, output, "isolated", "TR-E2E-WP1-GATEB-ISOLATED-test2").returncode != 0
    hashes.write_text(json.dumps({ROLES[0]: {"token_sha256": "bad"}}), encoding="utf-8")
    assert run_generator(hashes, tmp_path / "bad.env", "isolated", "TR-E2E-WP1-GATEB-ISOLATED-test3").returncode != 0
