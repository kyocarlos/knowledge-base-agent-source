from __future__ import annotations

import pytest

from app.core.config import AppSettings
from app.core.release_metadata import (
    validate_build_timestamp,
    validate_image_digest,
    validate_release_id,
    validate_source_commit,
)


def test_app_settings_reads_complete_release_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KM_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("KM_RELEASE_ID", "wp1-selfread-auth-20260831-r1")
    monkeypatch.setenv("KM_IMAGE_DIGEST", "sha256:" + "b" * 64)
    monkeypatch.setenv("KM_BUILD_TIMESTAMP", "2026-08-31T15:46:55.251425676+08:00")

    settings = AppSettings.from_env()

    assert settings.release_id == "wp1-selfread-auth-20260831-r1"
    assert settings.image_digest == "sha256:" + "b" * 64
    assert settings.build_timestamp == "2026-08-31T15:46:55.251425676+08:00"


def test_app_settings_rejects_partial_release_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KM_GIT_COMMIT", "a" * 40)
    monkeypatch.setenv("KM_RELEASE_ID", "wp1-selfread-auth-20260831-r1")
    monkeypatch.delenv("KM_IMAGE_DIGEST", raising=False)
    monkeypatch.delenv("KM_BUILD_TIMESTAMP", raising=False)

    with pytest.raises(ValueError, match="configured together"):
        AppSettings.from_env()


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
