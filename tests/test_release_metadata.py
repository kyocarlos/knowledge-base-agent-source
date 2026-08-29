from __future__ import annotations

import pytest

from app.core.release_metadata import (
    validate_build_timestamp,
    validate_image_digest,
    validate_release_id,
    validate_source_commit,
)


@pytest.mark.parametrize(
    "value",
    ["2026-08-24T06:47:20+08:00", "2026-08-23T22:47:20Z"],
)
def test_build_timestamp_accepts_rfc3339_timezone_forms(value: str) -> None:
    assert validate_build_timestamp(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "2026-08-24 06:47:20 +0800 CST",
        "2026-08-24T06:47:20",
        "2026-13-24T06:47:20+08:00",
        "not-a-timestamp",
        "",
    ],
)
def test_build_timestamp_rejects_invalid_or_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError):
        validate_build_timestamp(value)


def test_release_identity_fields_have_explicit_contracts() -> None:
    assert validate_source_commit("a" * 40) == "a" * 40
    assert validate_release_id("wp1-metadata-fix-20260824-r1") == "wp1-metadata-fix-20260824-r1"
    assert validate_image_digest("sha256:" + "b" * 64) == "sha256:" + "b" * 64


@pytest.mark.parametrize(
    ("validator", "value"),
    [
        (validate_source_commit, "abc123"),
        (validate_release_id, "release id with spaces"),
        (validate_image_digest, "sha256:short"),
    ],
)
def test_release_identity_fields_reject_invalid_values(validator, value: str) -> None:
    with pytest.raises(ValueError):
        validator(value)
