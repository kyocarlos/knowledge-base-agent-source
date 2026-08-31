from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
SERVICES = ("web", "celery_search_worker", "celery_ingest_worker", "celery_beat")


def _environment(service: str) -> dict[str, str]:
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    values = {}
    for entry in document["services"][service].get("environment", []):
        key, value = entry.split("=", 1)
        values[key] = value
    return values


def test_asset_root_is_wired_only_to_web() -> None:
    environments = {service: _environment(service) for service in SERVICES}
    assert environments["web"]["KB_ASSETS_ROOT"].startswith("${KB_ASSETS_ROOT:-")
    for service in SERVICES[1:]:
        assert "KB_ASSETS_ROOT" not in environments[service]


def test_deployment_example_declares_asset_root_without_e2e_enablement() -> None:
    example = (ROOT / "config/wp01-deployment.env.example").read_text(encoding="utf-8")
    assert "KB_ASSETS_ROOT=/home/da40_ai_gb10/knowledge-base/data/assets" in example
    assert "KB_E2E_WRITE_MODE_ENABLED" not in example
