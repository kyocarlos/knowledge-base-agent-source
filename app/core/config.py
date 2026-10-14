"""Typed, environment-driven settings for the API shell."""

from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.release_metadata import validate_release_identity


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
DEFAULT_SERVICE_NAME = "knowledge-base-api"
DEFAULT_VERSION = "1.0.0"
DEFAULT_ENVIRONMENT = "development"


def _read_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"true", "1"}


def _https_url(name: str, value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError(f"{name} must be an absolute HTTPS URL")
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class OIDCSettings:
    """Configuration only; no provisional client identity is ever supplied."""

    enabled: bool = False
    issuer: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None
    scopes: tuple[str, ...] = ("openid", "profile", "email")
    clock_skew_seconds: int = 60
    session_ttl_seconds: int = 600
    control_db_path: str = "data/km-control-auth.sqlite3"
    session_signing_key: str | None = None
    claim_mapping: tuple[tuple[str, str], ...] = (("user_id", "sub"), ("display_name", "name"), ("email", "email"))

    @classmethod
    def from_env(cls) -> "OIDCSettings":
        enabled = _read_bool("KM_OIDC_ENABLED")
        if not enabled:
            return cls(enabled=False)
        issuer = _https_url("KM_OIDC_ISSUER", os.getenv("KM_OIDC_ISSUER", "").strip())
        redirect_uri = _https_url("KM_OIDC_REDIRECT_URI", os.getenv("KM_OIDC_REDIRECT_URI", "").strip())
        client_id = os.getenv("KM_OIDC_CLIENT_ID", "").strip()
        client_secret = os.getenv("KM_OIDC_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise ValueError("KM_OIDC_CLIENT_ID and KM_OIDC_CLIENT_SECRET are required when OIDC is enabled")
        scopes = tuple(dict.fromkeys(os.getenv("KM_OIDC_SCOPES", "openid profile email").split()))
        if "openid" not in scopes:
            raise ValueError("KM_OIDC_SCOPES must include openid")
        skew = int(os.getenv("KM_OIDC_CLOCK_SKEW_SECONDS", "60"))
        ttl = int(os.getenv("KM_OIDC_SESSION_TTL_SECONDS", "600"))
        if not 0 <= skew <= 300 or not 60 <= ttl <= 1800:
            raise ValueError("OIDC clock skew or session TTL is outside the allowed range")
        session_key = os.getenv("KM_SESSION_SIGNING_KEY", "").strip()
        if len(session_key) < 32:
            raise ValueError("KM_SESSION_SIGNING_KEY must contain at least 32 characters when OIDC is enabled")
        try:
            raw_mapping = json.loads(os.getenv("KM_OIDC_CLAIM_MAPPING_JSON", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("KM_OIDC_CLAIM_MAPPING_JSON must be a JSON object") from exc
        if not isinstance(raw_mapping, dict) or any(not isinstance(k, str) or not isinstance(v, str) or not k or not v for k, v in raw_mapping.items()):
            raise ValueError("KM_OIDC_CLAIM_MAPPING_JSON must map non-empty strings to non-empty strings")
        mapping = {"user_id": "sub", "display_name": "name", "email": "email"} | raw_mapping
        return cls(enabled, issuer, client_id, client_secret, redirect_uri, scopes, skew, ttl,
                   os.getenv("KM_CONTROL_DB_PATH", "data/km-control-auth.sqlite3"), session_key, tuple(mapping.items()))


def _read_safe_env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not _SAFE_VALUE.fullmatch(value):
        raise ValueError(f"{name} contains unsupported characters")
    return value


@dataclass(frozen=True, slots=True)
class AppSettings:
    service_name: str = DEFAULT_SERVICE_NAME
    version: str = DEFAULT_VERSION
    environment: str = DEFAULT_ENVIRONMENT
    commit: str | None = None
    release_id: str | None = None
    image_digest: str | None = None
    build_timestamp: str | None = None
    oidc: OIDCSettings = OIDCSettings()

    @classmethod
    def from_env(cls) -> "AppSettings":
        commit = os.getenv("KM_GIT_COMMIT", "").strip() or None
        if commit is not None and not _SAFE_VALUE.fullmatch(commit):
            raise ValueError("KM_GIT_COMMIT contains unsupported characters")
        release_id = os.getenv("KM_RELEASE_ID", "").strip() or None
        image_digest = os.getenv("KM_IMAGE_DIGEST", "").strip() or None
        build_timestamp = os.getenv("KM_BUILD_TIMESTAMP", "").strip() or None
        metadata = (commit, release_id, image_digest, build_timestamp)
        if any(value is not None for value in metadata):
            if not all(value is not None for value in metadata):
                raise ValueError("release metadata must be configured together")
            validate_release_identity(
                source_commit=commit,
                release_id=release_id,
                image_digest=image_digest,
                build_timestamp=build_timestamp,
            )
        return cls(
            service_name=_read_safe_env("KM_SERVICE_NAME", DEFAULT_SERVICE_NAME),
            version=_read_safe_env("KM_APP_VERSION", DEFAULT_VERSION),
            environment=_read_safe_env("KM_ENVIRONMENT", DEFAULT_ENVIRONMENT),
            commit=commit,
            release_id=release_id,
            image_digest=image_digest,
            build_timestamp=build_timestamp,
            oidc=OIDCSettings.from_env(),
        )
