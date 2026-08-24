from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_image_build_context_copies_runtime_capability_sources() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY app/ ./app/" in dockerfile
    assert "COPY src/ ./src/" in dockerfile


def test_release_image_probe_checks_e2e_and_metadata_contracts() -> None:
    probe = (ROOT / "scripts/validate_release_image_capabilities.py").read_text(encoding="utf-8")
    for symbol in (
        "authenticate_report_agent",
        "authenticate_report_reviewer",
        "authenticate_e2e_agent",
        "authenticate_e2e_reviewer",
        "authenticate_e2e_cleanup",
        "validate_release_identity",
        "AppSettings.from_env",
    ):
        assert symbol in probe
