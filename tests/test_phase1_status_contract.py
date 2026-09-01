import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/phase1-status-manifest.json"
VALIDATOR = ROOT / "scripts/validate_phase1_status.py"


def load_manifest():
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_has_ordered_18_phase1_work_items():
    manifest = load_manifest()
    assert [item["wp_id"] for item in manifest["work_items"]] == [f"P1-WP{i:02d}" for i in range(1, 19)]
    assert all(item["status"] in manifest["statuses"] for item in manifest["work_items"])


def test_manifest_validator_passes():
    result = subprocess.run([sys.executable, str(VALIDATOR), str(MANIFEST)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"result": "PASS"' in result.stdout


def test_manifest_validator_rejects_secret_like_field(tmp_path):
    manifest = load_manifest()
    manifest["credential_password"] = "must-not-exist"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = subprocess.run([sys.executable, str(VALIDATOR), str(path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "secret-like" in result.stderr
