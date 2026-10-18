"""Fail-closed configuration for one isolated KM data plane.

An application process belongs to exactly one instance.  The instance is a
deployment property, never a request parameter, so a client cannot select a
different database by changing a URL, header, or WebSocket payload.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


VALID_INSTANCE_IDS = frozenset({"test", "da40", "rd2"})


class InstanceIsolationError(RuntimeError):
    """Raised when a deployment cannot prove which data plane it owns."""


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise InstanceIsolationError(f"missing required deployment setting: {name}")
    return value


def _require_absolute_path(name: str) -> Path:
    value = Path(_required_env(name)).expanduser()
    if not value.is_absolute():
        raise InstanceIsolationError(f"{name} must be an absolute path")
    return value


@dataclass(frozen=True)
class InstanceStoreConfig:
    """All stateful endpoints owned by a single KM entry."""

    instance_id: str
    neo4j_uri: str
    qdrant_url: str
    timescaledb_url: str
    registry_url: str
    redis_url: str
    redis_key_prefix: str
    upload_root: Path
    report_staging_root: Path
    assets_root: Path
    control_db_url: str

    @classmethod
    def from_environment(cls) -> "InstanceStoreConfig":
        instance_id = _required_env("KM_INSTANCE_ID").lower()
        if instance_id not in VALID_INSTANCE_IDS:
            raise InstanceIsolationError(
                f"KM_INSTANCE_ID must be one of {sorted(VALID_INSTANCE_IDS)}"
            )

        config = cls(
            instance_id=instance_id,
            neo4j_uri=_required_env("NEO4J_URI"),
            qdrant_url=_required_env("QDRANT_URL"),
            timescaledb_url=_required_env("TIMESCALEDB_URL"),
            registry_url=_required_env("KB_REPORT_REGISTRY_URL"),
            redis_url=_required_env("REDIS_URL"),
            redis_key_prefix=_required_env("KM_REDIS_KEY_PREFIX"),
            upload_root=_require_absolute_path("KB_INGEST_UPLOAD_ROOT"),
            report_staging_root=_require_absolute_path("KB_REPORT_STAGING_ROOT"),
            assets_root=_require_absolute_path("KB_ASSETS_ROOT"),
            control_db_url=_required_env("KM_CONTROL_DB_URL"),
        )
        expected_prefix = f"km:{instance_id}:"
        if config.redis_key_prefix != expected_prefix:
            raise InstanceIsolationError(
                "KM_REDIS_KEY_PREFIX must be exactly " + expected_prefix
            )
        _required_env("KM_ENTRY_SESSION_SIGNING_KEY")
        control_origin = _required_env("KM_CONTROL_PUBLIC_ORIGIN")
        if not control_origin.startswith("https://"):
            raise InstanceIsolationError("KM_CONTROL_PUBLIC_ORIGIN must use https")
        return config


def configured_instance_id() -> str | None:
    """Return the deployment instance without making legacy local tests fail."""
    value = os.getenv("KM_INSTANCE_ID", "").strip().lower()
    return value or None


def require_instance_config() -> InstanceStoreConfig:
    """Validate all deployment state before an isolated service starts."""
    return InstanceStoreConfig.from_environment()


def redis_key(instance_id: str, key: str) -> str:
    """Build a namespaced Redis key and reject caller-supplied instance values."""
    if instance_id not in VALID_INSTANCE_IDS:
        raise InstanceIsolationError("unknown KM instance")
    normalized = str(key).lstrip(":")
    if normalized.startswith("km:"):
        raise InstanceIsolationError("callers must pass an unprefixed Redis key")
    return f"km:{instance_id}:{normalized}"
