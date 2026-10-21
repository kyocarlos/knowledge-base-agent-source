"""Offline, fail-closed verifier for disabled Gate A preparation evidence."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_BYTES = 1 << 20
EXPECTED_BEARER_SHA256 = "9d4e25e54748b8453882d43e6c00921f0fa8caf6cebf72fce1cb91e36666a4be"
EXPECTED_SCOPES = ["real:test:run", "real:test:status", "real:test:cancel"]
TOP_LEVEL = {
    "schema_version", "validation", "captured_at", "decision", "safety", "contract",
    "credential", "proxy", "token_registry", "runtime", "acl_evidence", "blockers",
    "protected_runtime_acl_files",
}
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
ISO = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?)(Z|[+-]\d\d:\d\d)$")
WINDOWS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
FORBIDDEN_SECRET = re.compile(r"tskey-(?:auth|client)", re.I)
BEARER_VALUE = re.compile(r"authorization\s*[:=]?\s*bearer\s+[^\s,;\"']+", re.I)


class EvidenceError(ValueError):
    """A safe, non-payload-revealing validation failure."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("duplicate JSON object key")
        result[key] = value
    return result


def _regular_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("evidence must be a regular non-symlink file")
    try:
        if path.stat().st_size > MAX_BYTES:
            raise EvidenceError("evidence file exceeds 1 MiB")
        data = path.read_bytes()
    except EvidenceError:
        raise
    except OSError as exc:
        raise EvidenceError("cannot read evidence file") from exc
    if len(data) > MAX_BYTES:
        raise EvidenceError("evidence file exceeds 1 MiB")
    return data


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        raise EvidenceError(f"{label} is not a timestamp")
    match = ISO.fullmatch(value)
    if not match:
        raise EvidenceError(f"{label} must be timezone-aware ISO-8601")
    main, zone = match.groups()
    if "." in main:
        head, fraction = main.split(".", 1)
        main = f"{head}.{fraction[:6]}"
    try:
        parsed = datetime.fromisoformat(main + ("+00:00" if zone == "Z" else zone))
    except ValueError as exc:
        raise EvidenceError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceError(f"{label} must be timezone-aware")
    return parsed


def _object(value: Any, name: str, fields: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise EvidenceError(f"{name} fields are invalid")
    return value


def _bool(value: Any, name: str) -> None:
    if type(value) is not bool:
        raise EvidenceError(f"{name} must be boolean")


def _string(value: Any, name: str) -> None:
    if not isinstance(value, str):
        raise EvidenceError(f"{name} must be a string")


def _int(value: Any, name: str) -> None:
    if type(value) is not int:
        raise EvidenceError(f"{name} must be integer")


def _scan_strings(value: Any, key: str = "") -> None:
    if isinstance(value, dict):
        for child_key, child in value.items():
            _scan_strings(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            _scan_strings(child, key)
    elif isinstance(value, str):
        if FORBIDDEN_SECRET.search(value) or BEARER_VALUE.search(value):
            raise EvidenceError("secret-like material is not allowed")
        if key.lower() == "authorization" and re.match(r"^\s*bearer\s+\S+", value, re.I):
            raise EvidenceError("secret-like material is not allowed")
        suspicious = re.search(r"(?:token|secret|password|authorization|credential)", key, re.I)
        if suspicious and len(value) >= 32 and not HEX64.fullmatch(value) and not WINDOWS_PATH.match(value):
            raise EvidenceError("plaintext credential material is not allowed")


def _hash(value: Any, name: str) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise EvidenceError(f"{name} must be SHA-256 hex")


def validate_evidence(raw: Any, *, now: datetime | str | None = None, evidence_sha256: str | None = None) -> dict[str, Any]:
    """Validate a decoded evidence object and return a secret-free summary."""
    if not isinstance(raw, dict) or set(raw) != TOP_LEVEL:
        raise EvidenceError("top-level fields are invalid")
    _scan_strings(raw)
    if raw["schema_version"] != "1.0" or raw["validation"] != "disabled_gate_a_preparation" or raw["decision"] != "NO-GO":
        raise EvidenceError("evidence identity is invalid")
    captured = _parse_time(raw["captured_at"], "captured_at")
    runtime = _object(raw["runtime"], "runtime", {"config_path", "env_path", "enabled", "adapter", "allowed_km_ip", "public_origin", "ingest_enabled", "expiry", "expiry_source", "expiry_crosscheck"})
    expiry = _parse_time(runtime["expiry"], "runtime.expiry")
    delta = expiry - captured
    if delta <= delta.__class__(0) or delta > delta.__class__(hours=4):
        raise EvidenceError("expiry window is invalid")
    safety = _object(raw["safety"], "safety", {"anritsu_a2a_real_enabled", "adapter", "instrument_lock_acquired", "iperf_started", "km_ingest_started", "sidecar_started", "proxy_started", "serve_apply_performed"})
    for key, value in safety.items():
        if key == "adapter":
            if value != "disabled":
                raise EvidenceError("safety adapter is invalid")
        elif value is not False:
            raise EvidenceError("safety gate is not disabled")
    contract = _object(raw["contract"], "contract", {"poc_cases", "duration_seconds", "autoretry", "extra_fields", "formal_https_unchanged", "ingest_disabled_success"})
    if contract["poc_cases"] != ["sa_dl_tcp"] or contract["duration_seconds"] != "15..30" or contract["autoretry"] != "forbidden" or contract["extra_fields"] != "forbidden" or contract["formal_https_unchanged"] is not True or contract["ingest_disabled_success"] != "completed/completed/<sha256>/not-started":
        raise EvidenceError("contract is invalid")
    credential = _object(raw["credential"], "credential", {"path", "length", "sha256", "regular_non_symlink", "acl_inheritance_protected", "acl_rule_count"})
    _hash(credential["sha256"], "credential.sha256")
    _int(credential["length"], "credential.length")
    _int(credential["acl_rule_count"], "credential.acl_rule_count")
    if credential["length"] < 32 or credential["regular_non_symlink"] is not True or credential["acl_inheritance_protected"] is not True:
        raise EvidenceError("credential protection is invalid")
    proxy = _object(raw["proxy"], "proxy", {"rendered_path", "sentinel_replaced", "test", "git_ignored"})
    if proxy["sentinel_replaced"] is not True or proxy["test"] != "passed" or proxy["git_ignored"] is not True:
        raise EvidenceError("proxy evidence is invalid")
    registry = _object(raw["token_registry"], "token_registry", {"path", "sha256", "scopes", "plaintext_present", "reused_8790_or_ingest_token"})
    _hash(registry["sha256"], "token_registry.sha256")
    if registry["sha256"].lower() != EXPECTED_BEARER_SHA256 or registry["scopes"] != EXPECTED_SCOPES or registry["plaintext_present"] is not False or registry["reused_8790_or_ingest_token"] is not False:
        raise EvidenceError("token registry evidence is invalid")
    if credential["sha256"].lower() == EXPECTED_BEARER_SHA256:
        raise EvidenceError("proxy credential must differ from Bearer hash")
    if runtime["enabled"] is not False or runtime["adapter"] != "disabled" or runtime["allowed_km_ip"] != "100.65.63.58" or runtime["public_origin"] != "http://100.72.21.115:8792" or runtime["ingest_enabled"] is not False:
        raise EvidenceError("runtime is not disabled")
    cross = _object(runtime["expiry_crosscheck"], "expiry_crosscheck", {"env", "json", "evidence", "all_equal"})
    if cross != {**cross, "env": "ANRITSU_A2A_REAL_TAILSCALE_HTTP_POC_EXPIRES_AT", "json": "runtime.expiry (alias of poc_transport.expires_at)", "evidence": "runtime.expiry", "all_equal": True} or runtime["expiry_source"] != "gate-a-disabled.json.runtime.expiry":
        raise EvidenceError("expiry crosscheck is invalid")
    acl = _object(raw["acl_evidence"], "acl_evidence", {"independent_evidence_present", "required_source", "repository_notes_accepted"})
    if acl["independent_evidence_present"] is not False or acl["required_source"] != "external_audit_or_tailscale_policy" or acl["repository_notes_accepted"] is not False:
        raise EvidenceError("ACL evidence is invalid")
    if not isinstance(raw["blockers"], list) or not raw["blockers"] or not all(isinstance(item, str) for item in raw["blockers"]):
        raise EvidenceError("blockers are invalid")
    joined = " ".join(raw["blockers"]).lower()
    if "acl" not in joined or "no-go" not in joined:
        raise EvidenceError("blockers must state ACL and NO-GO")
    files = raw["protected_runtime_acl_files"]
    if not isinstance(files, list) or len(files) < 3:
        raise EvidenceError("protected runtime files are incomplete")
    required = {"registry", "env", "json"}
    seen: set[str] = set()
    for item in files:
        obj = _object(item, "protected runtime file", {"path", "inheritance_protected", "broad_rule_count", "rule_count"})
        path = str(obj["path"]).lower()
        seen.update(kind for kind, marker in (("registry", "real-token-registry.json"), ("env", ".env"), ("json", "gate-a-disabled.json")) if marker in path)
        _int(obj["broad_rule_count"], "broad_rule_count")
        _int(obj["rule_count"], "rule_count")
        if obj["inheritance_protected"] is not True or obj["broad_rule_count"] != 0:
            raise EvidenceError("protected runtime ACL is invalid")
    if not required <= seen:
        raise EvidenceError("required protected runtime files are missing")
    reference_now = _parse_time(now, "now") if isinstance(now, str) else now
    if reference_now is None:
        reference_now = datetime.now(timezone.utc)
    if reference_now.tzinfo is None or reference_now.utcoffset() is None:
        raise EvidenceError("now must be timezone-aware")
    return {"valid": True, "decision": "NO-GO", "captured_at": raw["captured_at"], "expiry": runtime["expiry"], "current_expiry_valid": reference_now < expiry, "acl_evidence_present": False, "token_registry_hash_match": True, "blockers": list(raw["blockers"]), "evidence_sha256": evidence_sha256 or ""}


def verify_file(path: Path, *, now: datetime | str | None = None) -> dict[str, Any]:
    data = _regular_bytes(path)
    digest = hashlib.sha256(data).hexdigest()
    try:
        raw = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError, EvidenceError) as exc:
        raise EvidenceError("evidence encoding or JSON is invalid") from exc
    return validate_evidence(raw, now=now, evidence_sha256=digest)


__all__ = ["EvidenceError", "validate_evidence", "verify_file"]
