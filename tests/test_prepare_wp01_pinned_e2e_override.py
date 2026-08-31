from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts/prepare_wp01_pinned_e2e_override.py"
SERVICES = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")


def _base_compose(path: Path) -> None:
    path.write_text(
        "services:\n" + "".join(f"  {service}:\n    image: base:{service}\n" for service in SERVICES),
        encoding="utf-8",
    )


def test_generated_override_is_deterministic_and_has_no_null_build(tmp_path):
    output = tmp_path / "pinned.yml"
    image = "candidate:exact"
    subprocess.run([sys.executable, str(SCRIPT), "--help"], check=True, capture_output=True, text=True)
    # The CLI's Docker image validation is intentionally outside this pure output test.
    namespace = {"__name__": "not_main"}
    exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), namespace)
    namespace["write_override"](output, image)
    first = output.read_text(encoding="utf-8")
    namespace["write_override"](output, image)
    assert output.read_text(encoding="utf-8") == first
    assert "build: null" not in first
    for service in SERVICES:
        assert f"  {service}:\n    image: {image}\n" in first


def test_generated_override_renders_with_production_and_isolated_base_files(tmp_path):
    namespace = {"__name__": "not_main"}
    exec(compile(SCRIPT.read_text(encoding="utf-8"), str(SCRIPT), "exec"), namespace)
    for profile in ("production", "isolated"):
        base = tmp_path / f"{profile}.yml"
        override = tmp_path / f"{profile}-pinned.yml"
        _base_compose(base)
        namespace["write_override"](override, "candidate@sha256:" + "a" * 64)
        subprocess.run(
            ["docker", "compose", "-p", f"wp1-override-{profile}", "-f", str(base), "-f", str(override), "config", "--quiet"],
            check=True,
            capture_output=True,
            text=True,
        )


def test_malformed_override_is_rejected_by_compose_schema(tmp_path):
    base = tmp_path / "base.yml"
    malformed = tmp_path / "malformed.yml"
    _base_compose(base)
    malformed.write_text("services:\n  celery_beat:\n    build: null\n", encoding="utf-8")
    result = subprocess.run(
        ["docker", "compose", "-p", "wp1-override-malformed", "-f", str(base), "-f", str(malformed), "config", "--quiet"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "build must be a string" in (result.stderr + result.stdout)
