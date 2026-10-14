from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from km_a2a_bridge.gate_a_evidence import EvidenceError, verify_file

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = {
    "schema_version": "1.0", "validation": "disabled_gate_a_preparation",
    "captured_at": "2026-08-14T08:06:53.3175999Z", "decision": "NO-GO",
    "safety": {"anritsu_a2a_real_enabled": False, "adapter": "disabled", "instrument_lock_acquired": False, "iperf_started": False, "km_ingest_started": False, "sidecar_started": False, "proxy_started": False, "serve_apply_performed": False},
    "contract": {"poc_cases": ["sa_dl_tcp"], "duration_seconds": "15..30", "autoretry": "forbidden", "extra_fields": "forbidden", "formal_https_unchanged": True, "ingest_disabled_success": "completed/completed/<sha256>/not-started"},
    "credential": {"path": "D:\\Anritsu_Control_API\\runtime-real-poc\\proxy-credential.secret", "length": 64, "sha256": "825545d9bb0761bfc43ea697d80fa5b7a29a5a270086f98f27087947ab4d318a", "regular_non_symlink": True, "acl_inheritance_protected": True, "acl_rule_count": 1},
    "proxy": {"rendered_path": "D:\\Anritsu_Control_API\\runtime-real-poc\\nginx.conf", "sentinel_replaced": True, "test": "passed", "git_ignored": True},
    "token_registry": {"path": "D:\\Anritsu_Control_API\\runtime-real-poc\\real-token-registry.json", "sha256": "9d4e25e54748b8453882d43e6c00921f0fa8caf6cebf72fce1cb91e36666a4be", "scopes": ["real:test:run", "real:test:status", "real:test:cancel"], "plaintext_present": False, "reused_8790_or_ingest_token": False},
    "runtime": {"config_path": "D:\\Anritsu_Control_API\\runtime-real-poc\\gate-a-disabled.json", "env_path": "D:\\Anritsu_Control_API\\runtime-real-poc\\gate-a-disabled.env", "enabled": False, "adapter": "disabled", "allowed_km_ip": "100.65.63.58", "public_origin": "http://100.72.21.115:8792", "ingest_enabled": False, "expiry": "2026-08-14T12:04:54.9800919Z", "expiry_source": "gate-a-disabled.json.runtime.expiry", "expiry_crosscheck": {"env": "ANRITSU_A2A_REAL_TAILSCALE_HTTP_POC_EXPIRES_AT", "json": "runtime.expiry (alias of poc_transport.expires_at)", "evidence": "runtime.expiry", "all_equal": True}},
    "acl_evidence": {"independent_evidence_present": False, "required_source": "external_audit_or_tailscale_policy", "repository_notes_accepted": False},
    "blockers": ["No independent ACL evidence proving KM 100.65.63.58 is restricted to tagged Anritsu peer TCP 8792", "KM remains NO-GO; 8792 must not be applied or started"],
    "protected_runtime_acl_files": [{"path": "D:\\Anritsu_Control_API\\runtime-real-poc\\real-token-registry.json", "inheritance_protected": True, "broad_rule_count": 0, "rule_count": 2}, {"path": "D:\\Anritsu_Control_API\\runtime-real-poc\\gate-a-disabled.env", "inheritance_protected": True, "broad_rule_count": 0, "rule_count": 2}, {"path": "D:\\Anritsu_Control_API\\runtime-real-poc\\gate-a-disabled.json", "inheritance_protected": True, "broad_rule_count": 0, "rule_count": 2}],
}


def write_fixture(tmp_path: Path, value: dict, *, bom: bool = False) -> Path:
    path = tmp_path / "evidence.json"
    data = json.dumps(value, ensure_ascii=False).encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data)
    return path


def test_valid_disabled_no_go_and_bom(tmp_path: Path) -> None:
    summary = verify_file(write_fixture(tmp_path, FIXTURE, bom=True), now="2026-08-14T10:00:00Z")
    assert summary["valid"] is True
    assert summary["decision"] == "NO-GO"
    assert summary["current_expiry_valid"] is True
    assert summary["token_registry_hash_match"] is True


@pytest.mark.parametrize("mutator", [
    lambda x: x["safety"].update(iperf_started=True),
    lambda x: x["contract"].update(poc_cases=["other"]),
    lambda x: x["runtime"].update(enabled=True),
    lambda x: x["runtime"].update(adapter="production"),
    lambda x: x["runtime"].update(allowed_km_ip="127.0.0.1"),
    lambda x: x["runtime"].update(ingest_enabled=True),
    lambda x: x["runtime"]["expiry_crosscheck"].update(all_equal=False),
    lambda x: x["acl_evidence"].update(independent_evidence_present=True),
    lambda x: x["acl_evidence"].update(repository_notes_accepted=True),
    lambda x: x.update(blockers=[]),
    lambda x: x["token_registry"].update(plaintext_present=True),
    lambda x: x["protected_runtime_acl_files"][0].update(broad_rule_count=1),
])
def test_important_fail_closed_fields(tmp_path: Path, mutator) -> None:
    value = deepcopy(FIXTURE)
    mutator(value)
    with pytest.raises(EvidenceError):
        verify_file(write_fixture(tmp_path, value))


def test_duplicate_keys_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
    with pytest.raises(EvidenceError):
        verify_file(path)


def test_symlink_rejected(tmp_path: Path) -> None:
    target = write_fixture(tmp_path, FIXTURE)
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(EvidenceError):
        verify_file(link)


def test_oversized_rejected(tmp_path: Path) -> None:
    path = tmp_path / "large.json"
    path.write_bytes(b"{" + b"a" * (1 << 20) + b"}")
    with pytest.raises(EvidenceError):
        verify_file(path)


@pytest.mark.parametrize("timestamp", ["2026-08-14T08:06:53Z", "2026-08-14T12:07:00Z"])
def test_expired_or_invalid_window_is_structural_error(tmp_path: Path, timestamp: str) -> None:
    value = deepcopy(FIXTURE)
    value["runtime"]["expiry"] = timestamp
    with pytest.raises(EvidenceError):
        verify_file(write_fixture(tmp_path, value))


def test_expired_history_remains_valid_but_not_current(tmp_path: Path) -> None:
    summary = verify_file(write_fixture(tmp_path, FIXTURE), now="2026-08-14T13:00:00Z")
    assert summary["valid"] is True
    assert summary["decision"] == "NO-GO"
    assert summary["current_expiry_valid"] is False


@pytest.mark.parametrize("payload", [
    {"token": "tskey-auth-abcdefghijklmnop"},
    {"authorization": "Bearer very-secret-value"},
    {"token": "x" * 40},
])
def test_secret_like_strings_rejected_without_echo(tmp_path: Path, payload: dict) -> None:
    value = deepcopy(FIXTURE)
    value["proxy"].update(payload)
    with pytest.raises(EvidenceError) as exc:
        verify_file(write_fixture(tmp_path, value))
    assert "tskey" not in str(exc.value).lower()
    assert "very-secret" not in str(exc.value)


def test_cli_is_secret_free_and_returns_summary(tmp_path: Path) -> None:
    path = write_fixture(tmp_path, FIXTURE)
    proc = subprocess.run([sys.executable, str(ROOT / "scripts/verify_anritsu_gate_a_evidence.py"), "--evidence-file", str(path), "--now", "2026-08-14T13:00:00Z"], capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result["decision"] == "NO-GO"
    assert result["current_expiry_valid"] is False
    assert "825545" not in proc.stdout


def test_root_fixture_is_optional() -> None:
    path = ROOT / "gate-a-disabled-preparation-20260814.json"
    if not path.exists():
        pytest.skip("optional root fixture is absent")
    assert verify_file(path)["decision"] == "NO-GO"
