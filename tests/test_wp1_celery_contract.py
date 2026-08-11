from app.core.job_config import JobStatus
from src.web_api.tasks import JOB_CONFIG, _normalise_task_state, celery_app


def test_celery_declares_new_queues_and_preserves_legacy_routes():
    queues = {queue.name for queue in celery_app.conf.task_queues}
    assert {JOB_CONFIG.default_queue, JOB_CONFIG.document_queue, JOB_CONFIG.indexing_queue} <= queues
    assert {"search", "ingest"} <= queues
    assert celery_app.conf.task_routes["tasks.search_task"]["queue"] == "search"
    assert celery_app.conf.task_routes["tasks.ingest_task"]["queue"] == "ingest"


def test_ingest_job_state_adds_canonical_status_without_breaking_legacy_status():
    state = _normalise_task_state({"task_id": "task-1", "status": "converting"})
    assert state["status"] == "converting"
    assert state["job_status"] == JobStatus.RUNNING
    assert _normalise_task_state({"status": "completed"})["job_status"] == JobStatus.SUCCEEDED
    assert _normalise_task_state({"status": "queued"})["job_status"] == JobStatus.QUEUED

