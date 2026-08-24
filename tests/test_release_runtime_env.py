from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/generate_release_runtime_env.py"


def test_release_runtime_env_is_validated_and_written(tmp_path: Path) -> None:
    output = tmp_path / "release.env"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--commit",
            "12328e19a089b62a15a2a31582b8f05e9ceaa503",
            "--release-id",
            "wp1-fix-20260822",
            "--image-digest",
            "sha256:" + "a" * 64,
            "--build-timestamp",
            "2026-08-22T12:53:13+08:00",
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "KM_GIT_COMMIT=12328e19a089b62a15a2a31582b8f05e9ceaa503" in output.read_text()
    assert "KM_RELEASE_ID=wp1-fix-20260822" in output.read_text()
    assert "KM_IMAGE_DIGEST=sha256:" + "a" * 64 in output.read_text()
    assert "KM_BUILD_TIMESTAMP=2026-08-22T12:53:13+08:00" in output.read_text()
    assert output.stat().st_mode & 0o777 == 0o600


def test_release_runtime_env_accepts_utc_z_timestamp(tmp_path: Path) -> None:
    output = tmp_path / "release-z.env"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--commit",
            "a" * 40,
            "--release-id",
            "wp1-fix-z",
            "--image-digest",
            "sha256:" + "b" * 64,
            "--build-timestamp",
            "2026-08-24T00:00:00Z",
            "--output",
            str(output),
        ],
        check=True,
    )
    assert "KM_BUILD_TIMESTAMP=2026-08-24T00:00:00Z" in output.read_text()


def test_release_runtime_env_rejects_invalid_commit(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--commit",
            "not-a-commit",
            "--release-id",
            "wp1-fix-20260822",
            "--image-digest",
            "sha256:" + "a" * 64,
            "--build-timestamp",
            "2026-08-22T12:53:13+08:00",
            "--output",
            str(tmp_path / "release.env"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_release_runtime_env_rejects_invalid_timestamp(tmp_path: Path) -> None:
    output = tmp_path / "invalid.env"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--commit",
            "a" * 40,
            "--release-id",
            "wp1-fix-20260824",
            "--image-digest",
            "sha256:" + "b" * 64,
            "--build-timestamp",
            "2026-08-24 06:47:20 +0800 CST",
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not output.exists()
