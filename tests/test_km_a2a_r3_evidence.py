from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from km_a2a_bridge.r3_evidence import R3Evidence, canonical_json, verify_evidence, verify_files

ROOT = Path(__file__).parents[1]
EXPECTED_EVIDENCE_SHA256 = "de0cdce6b74756e8e593fe981045b95f230f6c59e88f802ecad41ab4d6365951"
EXPECTED_CONTRACT_SHA256 = "33f7ffff032b92db4a4b975c715dafcecb9bdcabe96bd7eb4f5e8a4536a8204c"

BASE_EVIDENCE = {
    "agent_card": {
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "description": "Approval-gated real instrument endpoint; separate from dry-run.",
        "name": "Anritsu Agent Real-Run",
        "securityRequirements": [{"schemes": {"bearerAuth": {"list": [""]}}}],
        "securitySchemes": {"bearerAuth": {"scheme": "bearer", "type": "http"}},
        "skills": [{"id": "run_iperf_test_real", "name": "Run approved Anritsu iPerf test", "tags": ["anritsu", "real-run", "approval-required"]}],
        "supportedInterfaces": [{"protocolBinding": "JSONRPC", "protocolVersion": "1.0", "url": "https://anritsu-real.example.invalid:8792/a2a"}],
        "version": "1.0-real-r3",
        "x-anritsu-contract": {
            "a2a_protocol": "1.0",
            "canonicalization": "project-defined sorted-key JSON, UTF-8, compact separators",
            "digest_algorithm": "SHA-256",
            "digest_excludes": [],
            "json_rpc": "2.0",
            "schema": "1.0-real",
        },
    },
    "agent_card_sha256": "cf37544c6a295dd8afa1f197ee8169a0600927c0924b2c34aa102a8c0252245a",
    "canonicalization": "sorted-key JSON, UTF-8, compact separators, arrays retain order",
    "checks": {
        "a2a_jsonrpc": True,
        "bearer_scheme": True,
        "card_version": True,
        "disabled_gate": True,
        "missing_scope_403": True,
        "missing_token_401": True,
        "same_origin_a2a": True,
        "strict_extra_field_rejection": True,
        "unique_skill": True,
        "wrong_token_403": True,
    },
    "go_decision": "NO-GO",
    "mode": "in-process-fake-disabled",
    "network": {"external_connections": 0, "model": "TestClient in-process/no-listener invariant", "port_bound": False},
    "schema": "anritsu-real-run-r3-preflight-evidence-1",
    "side_effect_counters": {"execute": 0, "ingest": 0, "probe": 0, "safe_state": 0, "stop_iperf": 0},
}


def fixture() -> dict:
    return copy.deepcopy(BASE_EVIDENCE)


def evidence(value: dict | None = None) -> R3Evidence:
    raw = value or fixture()
    raw["agent_card_sha256"] = hashlib.sha256(canonical_json(raw["agent_card"])).hexdigest()
    return R3Evidence.model_validate(raw)


def test_equivalent_fixture_validates_and_is_fail_closed():
    item = evidence()
    assert verify_evidence(item).endswith(".invalid:8792")
    assert item.go_decision == "NO-GO"


@pytest.mark.parametrize("field", ["go_decision", "mode", "schema"])
def test_fixed_values_and_extra_fields_are_strict(field):
    raw = fixture()
    raw[field] = "GO" if field == "go_decision" else "wrong"
    with pytest.raises(ValidationError):
        R3Evidence.model_validate(raw)
    raw = fixture()
    raw["unexpected"] = 1
    with pytest.raises(ValidationError):
        R3Evidence.model_validate(raw)


@pytest.mark.parametrize("mutate", [
    lambda x: x.update(agent_card_sha256="0" * 64),
    lambda x: x["network"].update(external_connections=1),
    lambda x: x["network"].update(port_bound=True),
    lambda x: x["side_effect_counters"].update(execute=1),
    lambda x: x["checks"].update(a2a_jsonrpc=False),
    lambda x: x["checks"].pop("wrong_token_403"),
])
def test_digest_network_counters_and_checks_fail_closed(mutate):
    raw = fixture()
    mutate(raw)
    with pytest.raises((ValidationError, ValueError)):
        verify_evidence(R3Evidence.model_validate(raw))


@pytest.mark.parametrize("change", [
    lambda c: c["supportedInterfaces"].append({"url": "https://other.invalid/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}),
    lambda c: c["skills"].append({"id": "other"}),
    lambda c: c["securitySchemes"].clear(),
    lambda c: c.update(securityRequirements=[]),
    lambda c: c.update(version="wrong"),
    lambda c: c.update(token="secret"),
    lambda c: c["supportedInterfaces"][0].update(url="https://anritsu.example.com:8792/a2a"),
    lambda c: c["x-anritsu-contract"].update(json_rpc="1.0"),
])
def test_card_invariants_fail_closed(change):
    raw = fixture()
    change(raw["agent_card"])
    raw["agent_card_sha256"] = hashlib.sha256(canonical_json(raw["agent_card"])).hexdigest()
    with pytest.raises((ValidationError, ValueError)):
        verify_evidence(R3Evidence.model_validate(raw))


def test_files_and_cli_use_bytes_digests_without_network(tmp_path):
    ev = tmp_path / "evidence.json"
    contract = tmp_path / "contract.md"
    ev.write_bytes(json.dumps(fixture(), ensure_ascii=False, separators=(",", ":")).encode())
    contract.write_bytes(b"offline contract")
    eh = hashlib.sha256(ev.read_bytes()).hexdigest()
    ch = hashlib.sha256(contract.read_bytes()).hexdigest()
    summary = verify_files(ev, eh, contract, ch)
    assert summary["production_ready"] is False and summary["go_decision"] == "NO-GO"
    result = subprocess.run([sys.executable, "scripts/verify_anritsu_r3_evidence.py", "--evidence-file", str(ev), "--expected-evidence-sha256", eh, "--contract-file", str(contract), "--expected-contract-sha256", ch], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0
    assert json.loads(result.stdout)["production_ready"] is False


def test_files_reject_symlink_and_wrong_hash(tmp_path):
    ev = tmp_path / "evidence.json"
    contract = tmp_path / "contract.md"
    ev.write_text(json.dumps(fixture()), encoding="utf-8")
    contract.write_text("x", encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(ev)
    with pytest.raises(ValueError, match="non-symlink"):
        verify_files(link, "0" * 64, contract, hashlib.sha256(b"x").hexdigest())
    with pytest.raises(ValueError, match="mismatch"):
        verify_files(ev, "0" * 64, contract, hashlib.sha256(b"x").hexdigest())


def test_repository_handoff_files_match_recorded_hashes():
    summary = verify_files(
        ROOT / "r3-preflight.json",
        EXPECTED_EVIDENCE_SHA256,
        ROOT / "ANRITSU_A2A_REAL_RUN_R3_CONTRACT.md",
        EXPECTED_CONTRACT_SHA256,
    )
    assert summary["agent_card_sha256"] == BASE_EVIDENCE["agent_card_sha256"]
    assert summary["production_ready"] is False
