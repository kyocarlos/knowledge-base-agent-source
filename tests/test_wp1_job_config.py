import pytest
from fastapi.testclient import TestClient

from app.core.job_config import JobConfig, JobStatus, celery_headers
from app.main import create_app
from app.core.config import AppSettings
from src import web_api


def test_job_status_contract_is_stable():
    assert [status.value for status in JobStatus] == [
        "queued", "running", "succeeded", "failed", "retrying", "cancelled"
    ]


def test_job_config_reads_environment(monkeypatch):
    monkeypatch.setenv("KB_MAX_CONCURRENT_PROCESSING", "4")
    monkeypatch.setenv("KB_JOB_MAX_RETRIES", "2")
    monkeypatch.setenv("KB_CELERY_BEAT_ENABLED", "true")
    config = JobConfig.from_env()
    assert config.max_concurrent_processing == 4
    assert config.max_retries == 2
    assert config.beat_enabled is True


def test_job_config_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("KB_JOB_TIME_LIMIT_SECONDS", "0")
    with pytest.raises(ValueError, match="KB_JOB_TIME_LIMIT_SECONDS"):
        JobConfig.from_env()


def test_celery_headers_only_propagates_trace_id():
    assert celery_headers("trace-123") == {"trace_id": "trace-123"}
    assert celery_headers(None) == {}


def test_search_propagates_http_trace_header_to_celery(monkeypatch):
    captured = {}

    class SubmittedTask:
        id = "search-task-1"

    def fake_apply_async(*, args, kwargs, headers):
        captured.update({"args": args, "kwargs": kwargs, "headers": headers})
        return SubmittedTask()

    monkeypatch.setattr(web_api, "cache_get", lambda _key: None)
    monkeypatch.setattr(web_api.search_task, "apply_async", fake_apply_async)

    with TestClient(create_app(AppSettings(environment="test"))) as client:
        response = client.post(
            "/search",
            headers={"X-Trace-ID": "trace-http-123"},
            json={"query": "trace propagation", "mode": "basic", "sources_only": True},
        )

    assert response.status_code == 200
    assert response.json()["task_id"] == "search-task-1"
    assert captured["headers"] == {"trace_id": "trace-http-123"}
