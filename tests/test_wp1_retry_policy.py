from app.core.job_config import classify_job_error


def test_retry_policy_distinguishes_input_and_infrastructure_errors():
    assert classify_job_error(ValueError("bad workbook")).retryable is False
    assert classify_job_error(ConnectionError("redis unavailable")).retryable is True
    assert classify_job_error(TimeoutError("qdrant timeout")).reason == "transient_infrastructure"
