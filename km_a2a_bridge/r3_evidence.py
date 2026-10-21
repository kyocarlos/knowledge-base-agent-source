"""Offline, fail-closed verifier for Anritsu R3 preflight evidence."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator

SCHEMA = "anritsu-real-run-r3-preflight-evidence-1"
CANONICALIZATION = "sorted-key JSON, UTF-8, compact separators, arrays retain order"
CHECK_NAMES = (
    "a2a_jsonrpc", "bearer_scheme", "card_version", "disabled_gate",
    "missing_scope_403", "missing_token_401", "same_origin_a2a",
    "strict_extra_field_rejection", "unique_skill", "wrong_token_403",
)
COUNTER_NAMES = ("probe", "execute", "stop_iperf", "safe_state", "ingest")
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


class AgentInterface(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    protocolBinding: StrictStr
    protocolVersion: StrictStr
    url: StrictStr


class AgentSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: StrictStr
    name: StrictStr
    tags: list[StrictStr]


class ContractCardExtension(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    a2a_protocol: Literal["1.0"]
    canonicalization: Literal["project-defined sorted-key JSON, UTF-8, compact separators"]
    digest_algorithm: Literal["SHA-256"]
    digest_excludes: list[Any] = Field(max_length=0)
    json_rpc: Literal["2.0"]
    schema_: Literal["1.0-real"] = Field(alias="schema")


class AgentCard(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    defaultInputModes: list[StrictStr]
    defaultOutputModes: list[StrictStr]
    description: StrictStr
    name: StrictStr
    version: StrictStr
    supportedInterfaces: list[AgentInterface]
    skills: list[AgentSkill]
    securitySchemes: dict[str, Any]
    securityRequirements: list[dict[str, Any]]
    x_anritsu_contract: ContractCardExtension = Field(alias="x-anritsu-contract")

    @model_validator(mode="after")
    def _fixed_media_types(self) -> "AgentCard":
        if self.defaultInputModes != ["application/json"] or self.defaultOutputModes != ["application/json"]:
            raise ValueError("Agent Card media types are invalid")
        return self


class Checks(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    a2a_jsonrpc: StrictBool
    bearer_scheme: StrictBool
    card_version: StrictBool
    disabled_gate: StrictBool
    missing_scope_403: StrictBool
    missing_token_401: StrictBool
    same_origin_a2a: StrictBool
    strict_extra_field_rejection: StrictBool
    unique_skill: StrictBool
    wrong_token_403: StrictBool


class Network(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    external_connections: StrictInt
    model: StrictStr
    port_bound: StrictBool


class SideEffectCounters(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    probe: StrictInt
    execute: StrictInt
    stop_iperf: StrictInt
    safe_state: StrictInt
    ingest: StrictInt


class R3Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    agent_card: AgentCard
    agent_card_sha256: StrictStr
    canonicalization: Literal[CANONICALIZATION]
    checks: Checks
    go_decision: Literal["NO-GO"]
    mode: Literal["in-process-fake-disabled"]
    network: Network
    schema_: Literal[SCHEMA] = Field(alias="schema")
    side_effect_counters: SideEffectCounters


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sensitive(value: Any) -> bool:
    if isinstance(value, dict):
        prohibited = {"authorization", "password", "secret", "token"}
        return any(str(k).lower() in prohibited or _sensitive(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_sensitive(v) for v in value)
    return False


def _bearer(value: Any) -> bool:
    if isinstance(value, dict):
        if str(value.get("scheme", "")).lower() == "bearer":
            return True
        return any(_bearer(v) for v in value.values())
    if isinstance(value, list):
        return any(_bearer(v) for v in value)
    return False


def _references_scheme(value: Any, names: set[str]) -> bool:
    if isinstance(value, dict):
        if any(str(key) in names for key in value):
            return True
        return any(_references_scheme(child, names) for child in value.values())
    if isinstance(value, list):
        return any(_references_scheme(child, names) for child in value)
    return False


def validate_agent_card(card: AgentCard | dict[str, Any]) -> str:
    """Validate card invariants and return its declared origin.

    This is deliberately pure: it performs no DNS, socket, HTTP, or endpoint
    readiness check.  ``.invalid`` origins are therefore evidence fixtures,
    never production endpoints.
    """
    raw = card.model_dump(mode="python", by_alias=True) if isinstance(card, AgentCard) else card
    parsed_card = card if isinstance(card, AgentCard) else AgentCard.model_validate(card)
    if parsed_card.version != "1.0-real-r3":
        raise ValueError("Agent Card version is invalid")
    if _sensitive(raw):
        raise ValueError("Agent Card contains a sensitive field")
    if not parsed_card.supportedInterfaces:
        raise ValueError("Agent Card has no interfaces")
    origins: set[tuple[str, str, int]] = set()
    for interface in parsed_card.supportedInterfaces:
        u = urlsplit(interface.url)
        try:
            port = u.port or (443 if u.scheme.lower() == "https" else 80)
        except ValueError as exc:
            raise ValueError("Agent Card interface port is invalid") from exc
        if (u.scheme.lower() != "https" or not u.hostname or u.username or u.password
                or u.path != "/a2a" or u.query or u.fragment):
            raise ValueError("Agent Card interface must be HTTPS same-origin /a2a")
        origins.add((u.scheme.lower(), u.hostname.lower(), port))
    if len(origins) != 1:
        raise ValueError("Agent Card interfaces are not same-origin")
    if not any(i.protocolBinding == "JSONRPC" and i.protocolVersion == "1.0" for i in parsed_card.supportedInterfaces):
        raise ValueError("Agent Card lacks JSONRPC 1.0")
    if len(parsed_card.skills) != 1 or parsed_card.skills[0].id != "run_iperf_test_real":
        raise ValueError("Agent Card must contain one run_iperf_test_real skill")
    bearer_names = {name for name, scheme_value in parsed_card.securitySchemes.items() if _bearer(scheme_value)}
    if not bearer_names:
        raise ValueError("Agent Card lacks Bearer scheme")
    if not _references_scheme(parsed_card.securityRequirements, bearer_names):
        raise ValueError("Agent Card does not require its Bearer scheme")
    scheme, host, port = next(iter(origins))
    if not host.endswith(".invalid"):
        raise ValueError("in-process evidence must use a reserved .invalid origin")
    return f"{scheme}://{host}:{port}"


def verify_evidence(value: R3Evidence) -> str:
    """Validate cross-field evidence invariants and return card origin."""
    if value.agent_card_sha256.lower() != sha256_bytes(canonical_json(value.agent_card.model_dump(mode="python", by_alias=True))):
        raise ValueError("Agent Card digest mismatch")
    origin = validate_agent_card(value.agent_card)
    if value.network.external_connections != 0 or value.network.port_bound:
        raise ValueError("network evidence is not offline")
    if value.network.model != "TestClient in-process/no-listener invariant":
        raise ValueError("network model is invalid")
    if any(getattr(value.side_effect_counters, n) != 0 for n in COUNTER_NAMES):
        raise ValueError("side-effect counter is non-zero")
    if any(getattr(value.checks, n) is not True for n in CHECK_NAMES):
        raise ValueError("required check is false")
    return origin


def _regular(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular non-symlink file")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read {label}") from exc


def verify_files(evidence_file: Path, expected_evidence_sha256: str, contract_file: Path, expected_contract_sha256: str) -> dict[str, Any]:
    for name, digest in (("evidence", expected_evidence_sha256), ("contract", expected_contract_sha256)):
        if not _HEX64.fullmatch(digest):
            raise ValueError(f"{name} SHA-256 must be 64 hexadecimal characters")
    evidence_bytes = _regular(evidence_file, "evidence file")
    contract_bytes = _regular(contract_file, "contract file")
    evidence_digest = sha256_bytes(evidence_bytes)
    contract_digest = sha256_bytes(contract_bytes)
    if evidence_digest.lower() != expected_evidence_sha256.lower():
        raise ValueError("evidence SHA-256 mismatch")
    if contract_digest.lower() != expected_contract_sha256.lower():
        raise ValueError("contract SHA-256 mismatch")
    try:
        evidence = R3Evidence.model_validate_json(evidence_bytes)
    except (ValueError, TypeError) as exc:
        raise ValueError("evidence JSON/schema is invalid") from exc
    origin = verify_evidence(evidence)
    return {
        "evidence_sha256": evidence_digest,
        "contract_sha256": contract_digest,
        "agent_card_sha256": evidence.agent_card_sha256,
        "card_origin": origin,
        "schema": evidence.schema_,
        "mode": evidence.mode,
        "go_decision": evidence.go_decision,
        "external_connections": evidence.network.external_connections,
        "port_bound": evidence.network.port_bound,
        "side_effects_zero": True,
        "production_ready": False,
    }


__all__ = ["R3Evidence", "canonical_json", "sha256_bytes", "validate_agent_card", "verify_evidence", "verify_files"]
