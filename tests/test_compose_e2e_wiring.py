from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.yml"
E2E_KEYS = {
    "KB_E2E_WRITE_MODE_ENABLED",
    "KB_E2E_AGENT_TOKEN_HASHES_JSON",
    "KB_E2E_REVIEWER_TOKEN_HASHES_JSON",
    "KB_E2E_CLEANUP_ENABLED",
    "KB_E2E_CLEANUP_TOKEN_HASHES_JSON",
    "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX",
}
IDENTITY_CLEANUP_KEYS = E2E_KEYS - {"KB_E2E_WRITE_MODE_ENABLED"}


def _environment(service: str) -> dict[str, str]:
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    values = {}
    for entry in document["services"][service].get("environment", []):
        key, value = entry.split("=", 1)
        values[key] = value
    return values


def test_web_has_explicit_e2e_wiring_without_secret_values() -> None:
    environment = _environment("web")
    assert E2E_KEYS <= environment.keys()
    for key in E2E_KEYS:
        assert "${" in environment[key]


def test_ingest_worker_has_only_identity_cleanup_wiring() -> None:
    environment = _environment("celery_ingest_worker")
    assert IDENTITY_CLEANUP_KEYS <= environment.keys()
    assert "KB_E2E_WRITE_MODE_ENABLED" not in environment


def test_search_worker_and_beat_have_no_e2e_exposure() -> None:
    assert not (E2E_KEYS & _environment("celery_search_worker").keys())
    assert not (E2E_KEYS & _environment("celery_beat").keys())
