from pathlib import Path
import re


ROOT = Path(__file__).parents[1]
COMPOSE = ROOT / "docker-compose.yml"
ENV_EXAMPLE = ROOT / "config/wp01-deployment.env.example"
STAGING_MOUNT = "${KB_REPORT_STAGING_ROOT_HOST:-./data/report-staging}:/app/data/report-staging"


def service_block(text: str, service: str) -> str:
    marker = f"  {service}:\n"
    start = text.index(marker) + len(marker)
    remainder = text[start:]
    next_service = re.search(r"^  [A-Za-z0-9_-]+:\n", remainder, re.MULTILINE)
    return remainder if next_service is None else remainder[:next_service.start()]


def test_web_and_ingest_share_report_staging_mount() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    for service in ("web", "celery_ingest_worker"):
        assert STAGING_MOUNT in service_block(text, service)


def test_search_and_beat_do_not_receive_report_staging_mount() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    for service in ("celery_search_worker", "celery_beat"):
        assert STAGING_MOUNT not in service_block(text, service)


def test_staging_host_root_is_explicitly_configurable() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "KB_REPORT_STAGING_ROOT_HOST=./data/report-staging" in text
