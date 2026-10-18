from pathlib import Path
import re


COMPOSE = Path(__file__).parents[1] / "docker-compose.yml"
ENV_EXAMPLE = Path(__file__).parents[1] / "config/wp01-deployment.env.example"


def _service_block(text: str, service: str) -> str:
    marker = f"  {service}:\n"
    start = text.index(marker)
    rest = text[start + len(marker):]
    next_match = re.search(r"^  [A-Za-z0-9_-]+:\n", rest, re.MULTILINE)
    return rest if next_match is None else rest[:next_match.start()]


def test_asset_root_is_explicitly_wired_only_to_web():
    text = COMPOSE.read_text(encoding="utf-8")
    assert "KB_ASSETS_ROOT=${KB_ASSETS_ROOT:-/home/da40_ai_gb10/knowledge-base/data/assets}" in _service_block(text, "web")
    for service in ("redis", "report_registry", "neo4j", "celery_search_worker", "celery_ingest_worker", "celery_beat", "nginx"):
        assert "KB_ASSETS_ROOT" not in _service_block(text, service)


def test_asset_root_example_does_not_change_v26_runtime_contract():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "KB_ASSETS_ROOT=/home/da40_ai_gb10/knowledge-base/data/assets" in text
    assert "KB_E2E_WRITE_MODE_ENABLED" not in text
