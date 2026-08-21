"""Typed, environment-driven settings for the API shell."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
_SAFE_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SAFE_TIMESTAMP = re.compile(r"^[0-9TZ:._+/-]{1,64}$")
DEFAULT_SERVICE_NAME = "knowledge-base-api"
DEFAULT_VERSION = "1.0.0"
DEFAULT_ENVIRONMENT = "development"


def _read_safe_env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    if not _SAFE_VALUE.fullmatch(value):
        raise ValueError(f"{name} contains unsupported characters")
    return value


def _read_optional_env(name: str, pattern: re.Pattern[str]) -> str | None:
    value = os.getenv(name, "").strip()
    if not value or value == "unknown":
        return None
    if not pattern.fullmatch(value):
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
        return cls(
            service_name=_read_safe_env("KM_SERVICE_NAME", DEFAULT_SERVICE_NAME),
            version=_read_safe_env("KM_APP_VERSION", DEFAULT_VERSION),
            environment=_read_safe_env("KM_ENVIRONMENT", DEFAULT_ENVIRONMENT),
            commit=commit,
            release_id=_read_optional_env("KM_RELEASE_ID", _SAFE_VALUE),
            image_digest=_read_optional_env("KM_IMAGE_DIGEST", _SAFE_IMAGE_DIGEST),
            build_timestamp=_read_optional_env("KM_BUILD_TIMESTAMP", _SAFE_TIMESTAMP),
        )
