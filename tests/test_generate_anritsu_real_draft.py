from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_anritsu_real_draft.py"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT, text=True, capture_output=True)


def test_creates_strict_unapproved_poc_draft_atomically(tmp_path: Path) -> None:
    output = tmp_path / "draft.json"
    result = run_script("--requested-by", "operator-01", "--duration", "15", "--output", str(output))
    assert result.returncode == 0, result.stderr
    draft = json.loads(output.read_text(encoding="utf-8"))
    assert set(draft) == {"job_schema_version", "dry_run", "job_type", "environment", "profile_id", "run_id", "requested_by", "duration_seconds", "test_cases"}
    assert draft == {**draft, "dry_run": False, "profile_id": "ncq2200b2v-throughput-v1", "test_cases": ["sa_dl_tcp"]}
    assert "approval_id" not in draft
    assert "ingest" not in json.dumps(draft).lower()
    assert draft["run_id"].startswith("real-run-")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert not output.is_symlink() and output.is_file()
    assert "KM ingest: disabled" in result.stdout
    assert "approval_id: absent" in result.stdout


def test_refuses_overwrite_and_generates_new_run_ids(tmp_path: Path) -> None:
    output = tmp_path / "draft.json"
    first = run_script("--requested-by", "operator-01", "--duration", "30", "--output", str(output))
    second = run_script("--requested-by", "operator-01", "--duration", "30", "--output", str(output))
    assert first.returncode == 0
    assert second.returncode == 1
    assert "refusing to overwrite" in second.stderr
    assert json.loads(output.read_text(encoding="utf-8"))["run_id"] in first.stdout


def test_requires_explicit_requester_and_poc_duration(tmp_path: Path) -> None:
    output = tmp_path / "draft.json"
    missing = run_script("--duration", "15", "--output", str(output))
    too_short = run_script("--requested-by", "operator-01", "--duration", "14", "--output", str(output))
    too_long = run_script("--requested-by", "operator-01", "--duration", "31", "--output", str(output))
    assert missing.returncode == 2
    assert too_short.returncode == too_long.returncode == 1
    assert not output.exists()


def test_submit_requires_approval_id(tmp_path: Path) -> None:
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps({"job_schema_version": "1.0-real", "dry_run": False, "job_type": "run_iperf_test", "environment": "anritsu", "profile_id": "ncq2200b2v-throughput-v1", "run_id": "real-run-test", "requested_by": "operator-01", "duration_seconds": 15, "test_cases": ["sa_dl_tcp"]}), encoding="utf-8")
    draft.chmod(0o600)
    result = subprocess.run([sys.executable, "scripts/km_anritsu_real_command.py", "submit", "--approved-job-file", str(draft)], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 1
    assert "approval_id" in result.stderr
