"""Offline, fail-closed verifier for disabled Gate A execution evidence."""
from __future__ import annotations
import hashlib, json, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAX_BYTES = 1 << 20
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")
SECRET = re.compile(r"tskey-(?:auth|client)|authorization\s*[:=]?\s*bearer\s+\S+|\bbearer\s+\S{32,}", re.I)

class EvidenceError(ValueError):
    """Safe validation error; payload values are never included."""

def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result: raise EvidenceError("duplicate JSON object key")
        result[key] = value
    return result

def _read(path: Path) -> tuple[dict[str, Any], bytes]:
    if path.is_symlink() or not path.is_file(): raise EvidenceError("evidence must be a regular non-symlink file")
    try:
        if path.stat().st_size > MAX_BYTES: raise EvidenceError("evidence file exceeds 1 MiB")
        data = path.read_bytes()
    except EvidenceError: raise
    except OSError as exc: raise EvidenceError("cannot read evidence file") from exc
    if len(data) > MAX_BYTES: raise EvidenceError("evidence file exceeds 1 MiB")
    try: value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as exc: raise EvidenceError("evidence encoding or JSON is invalid") from exc
    if not isinstance(value, dict): raise EvidenceError("evidence JSON must be an object")
    return value, data

def _obj(value: Any, name: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields: raise EvidenceError(f"{name} fields are invalid")
    return value

def _time(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not ISO.fullmatch(value): raise EvidenceError(f"{name} must be timezone-aware ISO-8601")
    try: parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc: raise EvidenceError(f"{name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None: raise EvidenceError(f"{name} must be timezone-aware")
    return parsed

def _hash(value: Any, name: str) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value): raise EvidenceError(f"{name} must be SHA-256 hex")

def _scan(value: Any, key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items(): _scan(child, str(child_key))
    elif isinstance(value, list):
        for child in value: _scan(child, key)
    elif isinstance(value, str) and (SECRET.search(value) or (re.search(r"token|secret|password|credential|authorization", key, re.I) and len(value) >= 32 and not HEX64.fullmatch(value))):
        raise EvidenceError("secret-like material is not allowed")

def _validate_acl(acl: dict[str, Any]) -> None:
    _obj(acl, "ACL evidence", {"schema_version", "captured_at", "decision", "scope", "source", "peer", "saved_grants", "saved_test", "allow_any_anritsu_grant_present", "real_run_authorized", "next_authorized_step", "screenshots"})
    if acl["schema_version"] != "1.0" or acl["decision"] != "PASS" or acl["scope"] != "tailscale-control-plane-acl-only": raise EvidenceError("ACL identity is invalid")
    _time(acl["captured_at"], "ACL captured_at")
    if acl["source"] != {"type": "tailscale-admin-console", "tailnet_admin": "kusanagi.huang@gmail.com"}: raise EvidenceError("ACL source is invalid")
    if acl["peer"] != {"km_ip": "100.65.63.58", "anritsu_ip": "100.72.21.115", "anritsu_tag": "tag:anritsu-a2a-poc"}: raise EvidenceError("ACL peer is invalid")
    if acl["saved_grants"] != [{"src": ["100.65.63.58"], "dst": ["tag:anritsu-a2a-poc"], "ip": ["tcp:8790"]}, {"src": ["100.65.63.58"], "dst": ["tag:anritsu-a2a-poc"], "ip": ["TCP:8792"]}]: raise EvidenceError("ACL grants are invalid")
    if acl["saved_test"] != {"src": "100.65.63.58", "accept": ["TAG:ANRITSU-A2A-POC:8792"], "proto": "tcp"}: raise EvidenceError("ACL saved test is invalid")
    if acl["allow_any_anritsu_grant_present"] is not False or acl["real_run_authorized"] is not False or acl["next_authorized_step"] != "anritsu-apply-8792-and-disabled-transport-preflight": raise EvidenceError("ACL authorization is invalid")
    shots = _obj(acl["screenshots"], "ACL screenshots", {"policy-saved.png", "grants-json.png", "tests-saved.png", "tests-json.png"})
    for value in shots.values(): _hash(value, "screenshot hash")

def validate_execution(execution: Any, acl: Any, *, acl_sha256: str, now: datetime | str | None = None, evidence_sha256: str | None = None) -> dict[str, Any]:
    fields = {"schema_version", "validation", "captured_at", "decision", "acl", "expiry", "serve", "runtime", "gate_a_local", "side_effects", "blockers"}
    execution = _obj(execution, "execution", fields); _scan(execution)
    if execution["schema_version"] != "1.0" or execution["validation"] != "disabled_gate_a_execution" or execution["decision"] != "PARTIAL-PASS-NO-GO": raise EvidenceError("execution identity is invalid")
    captured = _time(execution["captured_at"], "captured_at")
    expiry = _obj(execution["expiry"], "expiry", {"value", "timezone_aware", "within_four_hours_at_capture", "all_equal"}); expiry_time = _time(expiry["value"], "expiry.value")
    if expiry["timezone_aware"] is not True or expiry["within_four_hours_at_capture"] is not True or not captured < expiry_time <= captured + timedelta(hours=4) or expiry["all_equal"] != ["gate-a-disabled.env", "gate-a-disabled.json", "this evidence"]: raise EvidenceError("expiry evidence is invalid")
    part = _obj(execution["acl"], "execution.acl", {
        "source", "protected_copy", "sha256", "schema_version", "decision", "km_ip",
        "anritsu_ip", "tag", "tcp_8792_grant", "allow_any", "real_run_authorized",
        "next_authorized_step", "screenshots_originals_present",
        "screenshot_hash_declarations_recomputed", "screenshot_note",
    }); _hash(part["sha256"], "execution.acl.sha256")
    if part["sha256"].lower() != acl_sha256.lower(): raise EvidenceError("ACL hash mismatch")
    expected = {"schema_version": acl["schema_version"], "decision": acl["decision"], "km_ip": acl["peer"]["km_ip"], "anritsu_ip": acl["peer"]["anritsu_ip"], "tag": acl["peer"]["anritsu_tag"], "tcp_8792_grant": True, "allow_any": False, "real_run_authorized": False, "next_authorized_step": acl["next_authorized_step"]}
    if {key: part[key] for key in expected} != expected: raise EvidenceError("execution and ACL declarations differ")
    if (
        part["source"] != r"C:\Users\SSNR\Desktop\tailscale-acl-gate-result.json"
        or part["protected_copy"] != "a2a-sidecar/runtime/evidence/tailscale-acl-gate-result-20260814.json"
        or part["screenshots_originals_present"] is not False
        or part["screenshot_hash_declarations_recomputed"] is not False
        or part["screenshot_note"] != "Original screenshot files are not present locally; JSON is KM formal POC ACL result."
    ):
        raise EvidenceError("ACL provenance evidence is invalid")
    if execution["serve"] != {"stage": "passed", "validate": "passed", "apply": "passed", "tcp_8790": "127.0.0.1:8791", "tcp_8792": "127.0.0.1:8793", "rollback": "not performed"}: raise EvidenceError("serve evidence is invalid")
    if execution["runtime"] != {"real_enabled": False, "adapter": "disabled", "instrument_access": False, "ingest_enabled": False, "sidecar": "running on 127.0.0.1:8792", "proxy": "running in existing anritsu-a2a-tailscale-poc namespace", "health": "passed", "agent_card": "passed; exact x-anritsu-transport expiry matched", "port_8790": "preserved", "port_8792": "reachable through proxy namespace"}: raise EvidenceError("runtime evidence is invalid")
    if execution["gate_a_local"] != {"missing_bearer": 401, "wrong_bearer": 403, "correct_bearer_503_status_cancel": "awaiting KM cross-machine; Bearer plaintext unavailable and not generated"}: raise EvidenceError("local Gate A evidence is invalid")
    if execution["side_effects"] != {"journal_rows": 0, "lease_rows": 0, "approval_rows": 0, "instrument": False, "iperf": False, "excel": False, "km_ingest": False}: raise EvidenceError("side effects are non-zero")
    blockers = execution["blockers"]
    if blockers != [
        "Correct Bearer 503/status/cancel require KM cross-machine verification.",
        "No formal real-run GO is implied by this disabled transport preflight.",
    ]:
        raise EvidenceError("blockers are invalid")
    reference = _time(now, "now") if isinstance(now, str) else (now or datetime.now(timezone.utc))
    if reference.tzinfo is None or reference.utcoffset() is None: raise EvidenceError("now must be timezone-aware")
    return {"valid": True, "decision": execution["decision"], "captured_at": execution["captured_at"], "expiry": expiry["value"], "current_expiry_valid": reference < expiry_time, "acl_hash_match": True, "serve_apply": True, "runtime_disabled": True, "local_401_403_pass": True, "correct_bearer_cross_machine_pending": True, "side_effects_zero": True, "real_run_authorized": False, "evidence_sha256": evidence_sha256 or "", "blockers": list(blockers)}

def verify_files(execution_path: Path, acl_path: Path, *, now: datetime | str | None = None) -> dict[str, Any]:
    execution, execution_bytes = _read(execution_path); acl, acl_bytes = _read(acl_path); _scan(acl); _validate_acl(acl)
    return validate_execution(execution, acl, acl_sha256=hashlib.sha256(acl_bytes).hexdigest(), now=now, evidence_sha256=hashlib.sha256(execution_bytes).hexdigest())

__all__ = ["EvidenceError", "validate_execution", "verify_files"]
