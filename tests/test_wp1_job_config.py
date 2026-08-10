import pytest

from app.core.job_config import JobConfig, JobStatus, celery_headers


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
