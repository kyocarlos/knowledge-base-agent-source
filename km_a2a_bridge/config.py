"""Configuration contracts for the A2A bridge (no I/O or persistence)."""

import json
import os
import re
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

_ENVIRONMENTS = frozenset({"anritsu", "amarisoft"})
_SHA256 = re.compile(r"^[a-fA-F0-9]{64}$")


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    enabled: bool = False
    allowed_profiles: dict[str, frozenset[str]] = Field(
        default_factory=lambda: {"anritsu": frozenset(), "amarisoft": frozenset()}
    )
    agent_endpoints: dict[str, str] = Field(default_factory=dict)
    agent_credentials: dict[str, SecretStr] = Field(default_factory=dict, repr=False)
    control_token_sha256: SecretStr | None = Field(default=None, repr=False)
    journal_path: Path = Path("/tmp/km-a2a-bridge/tasks.sqlite3")
    transport_mode: str = "mock"

    @field_validator("allowed_profiles", mode="before")
    @classmethod
    def _profiles(cls, value: Mapping[str, object]) -> dict[str, frozenset[str]]:
        if not isinstance(value, Mapping):
            raise ValueError("allowed_profiles must be a mapping")
        if any(isinstance(profiles, (str, bytes)) for profiles in value.values()):
            raise ValueError("allowed profile values must be collections")
        result = {str(env): frozenset(str(p).strip() for p in profiles) for env, profiles in value.items()}
        unknown = set(result) - _ENVIRONMENTS
        if unknown:
            raise ValueError(f"unsupported profile environments: {sorted(unknown)}")
        if any(not profile for profiles in result.values() for profile in profiles):
            raise ValueError("allowed profile identifiers must not be blank")
        return result

    @field_validator("agent_credentials", mode="before")
    @classmethod
    def _credentials(cls, value: Mapping[str, object]) -> dict[str, SecretStr]:
        if not isinstance(value, Mapping):
            raise ValueError("agent_credentials must be a mapping")
        return {str(k): SecretStr(str(v)) for k, v in value.items()}

    @model_validator(mode="after")
    def _enabled_requirements(self) -> "BridgeConfig":
        if self.enabled:
            if self.transport_mode not in {"mock", "sdk-dry-run"}:
                raise ValueError("transport must be mock or sdk-dry-run")
            control_hash = self.control_token_sha256.get_secret_value() if self.control_token_sha256 else ""
            if not _SHA256.fullmatch(control_hash):
                raise ValueError("enabled bridge requires a SHA-256 control token hash")
            if not self.agent_endpoints:
                raise ValueError("enabled bridge requires at least one agent endpoint")
            unknown = set(self.agent_endpoints) - _ENVIRONMENTS
            if unknown:
                raise ValueError(f"unsupported agent environments: {sorted(unknown)}")
            for agent, endpoint in self.agent_endpoints.items():
                parsed = urlsplit(endpoint)
                if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
                    raise ValueError(f"agent endpoint for {agent} must be an HTTPS discovery base URL")
                credential = self.agent_credentials.get(agent)
                if credential is None or not credential.get_secret_value().strip():
                    raise ValueError(f"missing credential for agent {agent}")
            missing = set(self.agent_credentials) - set(self.agent_endpoints)
            if missing:
                raise ValueError(f"credentials without endpoints: {sorted(missing)}")
            values = [value.get_secret_value().strip() for value in self.agent_credentials.values()]
            if len(values) != len(set(values)):
                raise ValueError("each agent must have a distinct credential")
        return self

    @classmethod
    def from_env(cls) -> "BridgeConfig":
        """Load explicit bridge settings from KM_A2A_* environment variables."""
        enabled = os.getenv("KM_A2A_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        profiles_raw = os.getenv("KM_A2A_ALLOWED_PROFILES", "{}")
        endpoints_raw = os.getenv("KM_A2A_AGENT_ENDPOINTS", "{}")
        credentials_raw = os.getenv("KM_A2A_AGENT_CREDENTIALS", "{}")
        try:
            profiles = json.loads(profiles_raw)
            endpoints = json.loads(endpoints_raw)
            credentials = json.loads(credentials_raw)
        except json.JSONDecodeError as exc:
            raise ValueError("invalid JSON in KM_A2A configuration") from exc
        return cls(
            enabled=enabled,
            allowed_profiles=profiles,
            agent_endpoints=endpoints,
            agent_credentials=credentials,
            control_token_sha256=os.getenv("KM_A2A_CONTROL_TOKEN_SHA256") or None,
            journal_path=os.getenv("KM_A2A_JOURNAL_PATH", "/tmp/km-a2a-bridge/tasks.sqlite3"),
            transport_mode=os.getenv("KM_A2A_TRANSPORT", "mock"),
        )

    def __repr__(self) -> str:
        return (
            f"BridgeConfig(enabled={self.enabled!r}, allowed_profiles={self.allowed_profiles!r}, "
            f"agent_endpoints={self.agent_endpoints!r}, agent_credentials=<redacted>, "
            f"control_token_sha256=<redacted>, journal_path={self.journal_path!r}, "
            f"transport_mode={self.transport_mode!r})"
        )
