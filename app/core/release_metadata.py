"""Validation contract for non-secret release identity metadata."""

from __future__ import annotations

import re
from datetime import datetime


SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
RELEASE_ID = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
RFC3339_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$"
)


def validate_source_commit(value: str) -> str:
    if not SOURCE_COMMIT.fullmatch(value):
        raise ValueError("source commit must be 40 lowercase hexadecimal characters")
    return value


def validate_release_id(value: str) -> str:
    if not RELEASE_ID.fullmatch(value):
        raise ValueError("release ID contains unsupported characters")
    return value


def validate_image_digest(value: str) -> str:
    if not IMAGE_DIGEST.fullmatch(value):
        raise ValueError("image digest must use sha256:<64 lowercase hex>")
    return value


def validate_build_timestamp(value: str) -> str:
    """Require an RFC3339 timestamp with an explicit UTC designator or offset."""

    if not RFC3339_TIMESTAMP.fullmatch(value):
        raise ValueError("build timestamp must be RFC3339 with T and an explicit timezone")
    parseable = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(parseable)
    except ValueError as exc:
        raise ValueError("build timestamp is not a valid calendar timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("build timestamp must include a timezone")
    return value


def validate_release_identity(
    *, source_commit: str, release_id: str, image_digest: str, build_timestamp: str
) -> dict[str, str]:
    return {
        "KM_GIT_COMMIT": validate_source_commit(source_commit),
        "KM_RELEASE_ID": validate_release_id(release_id),
        "KM_IMAGE_DIGEST": validate_image_digest(image_digest),
        "KM_BUILD_TIMESTAMP": validate_build_timestamp(build_timestamp),
    }
