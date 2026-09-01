import json
import importlib.util
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


def test_manifest_separates_accepted_and_deployed_release():
    manifest = load_manifest()
    assert "approved_release" not in manifest
    assert manifest["accepted_release"]["historical_acceptance_run"]
    deployed = manifest["deployed_release"]
    assert deployed["deployment_state"] == "BASELINE"
    assert set(deployed["service_images"]) == {
        "kb-web", "kb-celery-search", "kb-celery-ingest", "kb-celery-beat"
    }


def test_baseline_reconciliation_uses_deployed_service_images():
    spec = importlib.util.spec_from_file_location("collector", ROOT / "scripts/collect_phase1_runtime_status.py")
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    manifest = load_manifest()
    images = manifest["deployed_release"]["service_images"]
    snapshot = {
        "git": {"head": None, "clean": False},
        "version": {"health_status": 200, "version_status": 200, "data": {}},
        "services": {name: {"status": "running", "image_id": image} for name, image in images.items()},
    }
    assert collector.compare(manifest, snapshot) == "PASS"
    snapshot["services"]["kb-web"]["image_id"] = "sha256:" + "0" * 64
    assert collector.compare(manifest, snapshot) == "MISMATCH"


def test_manifest_validator_rejects_secret_like_field(tmp_path):
    manifest = load_manifest()
    manifest["credential_password"] = "must-not-exist"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = subprocess.run([sys.executable, str(VALIDATOR), str(path)], capture_output=True, text=True)
    assert result.returncode != 0
    assert "secret-like" in result.stderr


def test_collector_supports_broker_mode_without_direct_probe_requirements():
    source = (ROOT / "scripts/collect_phase1_runtime_status.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/phase1-runtime-status.yml").read_text(encoding="utf-8")
    assert "--broker-socket" in source
    assert "broker mode cannot be combined with direct host probes" in source
    assert "--broker-socket /run/km-status-broker/status.sock" in workflow
    assert "docker inspect" not in workflow


def test_broker_exposes_only_fixed_status_endpoint():
    source = (ROOT / "scripts/km_status_broker.py").read_text(encoding="utf-8")
    assert 'request != "GET /v1/status HTTP/1.1"' in source
    assert "container.exec" not in source
    assert '"secrets_included": False' in source


def test_host_installer_is_root_only_and_does_not_start_by_default():
    source = (ROOT / "scripts/install_km_status_runner_host.sh").read_text(encoding="utf-8")
    assert 'id -u' in source
    assert "if [ \"${1:-}\" = --start ]" in source
    assert "service_start=NOT_REQUESTED" in source
    assert "docker" in source
