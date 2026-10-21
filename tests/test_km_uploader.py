from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.test_reports.km_uploader import KMAuth, KMReportClient, UploadWorkflowError, request_verify


def response(status: int, body: dict):
    item = Mock()
    item.status_code = status
    item.json.return_value = body
    return item


def test_test_only_auto_approval_requires_prefix():
    session = Mock()
    session.post.return_value = response(200, {"status": "queued"})
    client = KMReportClient("https://km.example", KMAuth("agent", "token", "reviewer", "review", True, "TR-"), session=session)
    assert client.approve_test_only("submission-1", "TR-001")["status"] == "queued"
    with pytest.raises(UploadWorkflowError, match="disposable test runs"):
        client.approve_test_only("submission-1", "PROD-001")


def test_production_auth_cannot_auto_approve():
    client = KMReportClient("https://km.example", KMAuth("agent", "token", "reviewer", "review", False, None))
    with pytest.raises(UploadWorkflowError, match="disposable test runs"):
        client.approve_test_only("submission-1", "TR-001")


def test_wait_for_completion_returns_terminal_state_without_sleep():
    session = Mock()
    session.get.side_effect = [response(200, {"status": "queued"}), response(200, {"status": "completed", "ingest_task_id": "task-1"})]
    client = KMReportClient("https://km.example", KMAuth("agent", "token"), session=session)
    result = client.wait_for_completion("submission-1", "TR-001", attempts=2, interval=0, sleeper=lambda _: None)
    assert result["status"] == "completed"


def test_wait_timeout_is_explicit():
    session = Mock()
    session.get.return_value = response(200, {"status": "queued"})
    client = KMReportClient("https://km.example", KMAuth("agent", "token"), session=session)
    with pytest.raises(UploadWorkflowError, match="polling timeout"):
        client.wait_for_completion("submission-1", "TR-001", attempts=2, interval=0, sleeper=lambda _: None)


def test_request_verify_requires_explicit_insecure_opt_in():
    assert request_verify({}) is True
    assert request_verify({"KB_INGEST_ALLOW_INSECURE_TLS": "true"}) is False
    assert request_verify({"KB_CA_CERT": "/etc/ssl/km-ca.pem", "KB_INGEST_ALLOW_INSECURE_TLS": "true"}) == "/etc/ssl/km-ca.pem"
