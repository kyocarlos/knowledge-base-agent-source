"""Typed, environment-driven settings for the API shell."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from app.core.release_metadata import validate_release_identity


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
DEFAULT_SERVICE_NAME = "knowledge-base-api"
DEFAULT_VERSION = "1.0.0"
DEFAULT_ENVIRONMENT = "development"


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
        )
