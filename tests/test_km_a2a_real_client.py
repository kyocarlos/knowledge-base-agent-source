from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from km_a2a_bridge.real_client import (
    ApprovedRealRunJob,
    RealClientConfig,
    RealRunClient,
    RealRunDispatchUnavailable,
    RealRunProtocolError,
    agent_card_digest,
    canonical_json,
)


def payload(**overrides):
    value = {"job_schema_version": "1.0-real", "dry_run": False, "job_type": "run_iperf_test", "environment": "anritsu", "profile_id": "ncq2200b2v-throughput-v1", "run_id": "run-20260814-001", "requested_by": "operator-01", "duration_seconds": 60, "test_cases": ["sa_dl_tcp"], "approval_id": "approval-0001"}
    value.update(overrides)
    return value


def card(**overrides):
    value = {
        "version": "1.0-real-r3",
        "supportedInterfaces": [{"url": "https://anritsu.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
        "skills": [{"id": "run_iperf_test_real"}],
        "securitySchemes": {"bearerAuth": {"httpAuthSecurityScheme": {"scheme": "bearer", "bearerFormat": "Bearer"}}},
        "securityRequirements": [{"schemes": {"bearerAuth": {"list": [""]}}}],
    }
    value.update(overrides)
    return value


def task(run_id="run-20260814-001", task_id="task-1", context_id="ctx-1"):
    return {"task": {"id": task_id, "contextId": context_id, "metadata": {"run_id": run_id, "context_id": context_id, "a2a_task_id": task_id, "approval_id": "approval-0001", "test_status": "pending", "report_status": "pending", "ingest_status": "pending"}}}


def setup_client(tmp_path, handler, *, enabled=True):
    token = tmp_path / "token"
    token.write_text("secret-token", encoding="utf-8")
    token.chmod(0o600)
    ca = tmp_path / "ca.pem"
    ca.write_text("CA", encoding="utf-8")
    calls = []

    def transport(request):
        calls.append(request)
        return handler(request)

    client = RealRunClient(RealClientConfig(enabled=enabled, security_approved=True, endpoint="https://anritsu.example", token_file=token, ca_file=ca), http_transport=httpx.MockTransport(transport))
    return client, calls


def setup_poc_client(tmp_path, handler, *, endpoint="http://100.65.63.58:8792", expires_at=None, now=None):
    token = tmp_path / "poc-token"
    token.write_text("secret-token", encoding="utf-8")
    token.chmod(0o600)
    calls = []

    def transport(request):
        calls.append(request)
        return handler(request)

    expiry = expires_at or (datetime.now(timezone.utc) + timedelta(hours=1))
    client = RealRunClient(
        RealClientConfig(
            enabled=True,
            security_approved=True,
            tailscale_http_poc=True,
            tailscale_http_poc_expires_at=expiry,
            endpoint=endpoint,
            token_file=token,
        ),
        http_transport=httpx.MockTransport(transport),
        now=now,
    )
    return client, calls, expiry


def poc_card(expires_at, **overrides):
    value = card(supportedInterfaces=[{"url": "http://100.65.63.58:8792/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}])
    value["x-anritsu-transport"] = {"mode": "tailscale-http-poc", "tailnet_only": True, "expires_at": expires_at.isoformat()}
    value.update(overrides)
    return value


def test_schema_and_digest_are_strict_and_deterministic():
    assert ApprovedRealRunJob.model_validate(payload()).run_id == "run-20260814-001"
    assert ApprovedRealRunJob.model_validate(payload(duration_seconds=300)).duration_seconds == 300
    with pytest.raises(ValidationError):
        ApprovedRealRunJob.model_validate(payload(duration_seconds=301))
    with pytest.raises(ValidationError):
        ApprovedRealRunJob.model_validate(payload(command="iperf"))
    with pytest.raises(ValidationError):
        ApprovedRealRunJob.model_validate(payload(autoretry=True))
    assert canonical_json({"b": 1, "a": "é"}) == '{"a":"é","b":1}'.encode()
    assert agent_card_digest({"b": 1, "a": "é"}) == agent_card_digest({"a": "é", "b": 1})


def test_approved_job_file_requires_0600_without_leaking_contents(tmp_path):
    job_file = tmp_path / "approved.json"
    job_file.write_text(json.dumps(payload(approval_id="secret-approval")), encoding="utf-8")
    job_file.chmod(0o644)
    with pytest.raises(ValueError) as exc:
        RealRunClient.load_approved_job(job_file)
    assert str(exc.value) == "approved job file must have mode 0600"
    assert "secret-approval" not in str(exc.value)


@pytest.mark.parametrize(
    "change",
    [
        {"version": "1.0-real"},
        {"supportedInterfaces": [{"url": "https://other/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]},
        {"supportedInterfaces": [{"url": "https://user@anritsu.example/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]},
        {"supportedInterfaces": [{"url": "https://anritsu.example:bad/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]},
        {"skills": [{"id": "run_iperf_test_real"}, {"id": "extra"}]},
        {"skills": [{"id": "run_iperf_test_real"}, "invalid"]},
        {"securitySchemes": {}},
        {"securityRequirements": [{"schemes": {"otherAuth": {"list": [""]}}}]},
        {"token": "must-not-be-in-card"},
    ],
)
def test_invalid_cards_are_rejected(tmp_path, change):
    def handler(request):
        return httpx.Response(200, json=card(**change))

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError, match="Agent Card"):
        client.submit(ApprovedRealRunJob.model_validate(payload()))


def test_three_methods_use_exact_json_rpc_envelopes(tmp_path):
    seen = []

    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        body = json.loads(request.content)
        seen.append(body)
        if body["method"] == "message/send":
            assert set(body) == {"jsonrpc", "id", "method", "params"}
            assert set(body["params"]) == {"message"}
            assert set(body["params"]["message"]) == {"messageId", "role", "parts"}
            assert body["params"]["message"]["role"] == "ROLE_USER"
            assert len(body["params"]["message"]["parts"]) == 1
            assert body["params"]["message"]["parts"][0]["data"] == payload()
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": task()})
        assert set(body["params"]) == {"id"}
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": task()})

    client, calls = setup_client(tmp_path, handler)
    job = ApprovedRealRunJob.model_validate(payload())
    assert client.submit(job)["id"] == "task-1"
    assert client.status("task-1")["id"] == "task-1"
    assert client.cancel("task-1")["id"] == "task-1"
    assert [x["method"] for x in seen] == ["message/send", "tasks/get", "tasks/cancel"]
    assert all(x.headers["authorization"] == "Bearer secret-token" for x in calls)
    assert all(x.headers["a2a-version"] == "1.0" for x in calls)
    assert calls[0].headers.get("content-type") is None
    assert all(x.headers["content-type"] == "application/json" for x in calls[1:])


@pytest.mark.parametrize("status,code", [(401, "authentication_required"), (403, "forbidden"), (503, "real_run_gate_closed")])
def test_http_stable_errors_are_typed_and_secret_free(tmp_path, status, code):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        return httpx.Response(status, text="secret-token")

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError) as exc:
        client.status("task-1")
    assert exc.value.code == code
    assert "secret-token" not in str(exc.value)


def test_correlation_mismatch_and_separated_statuses_rejected(tmp_path):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        request_body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_body["id"], "result": task(run_id="other")})

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError, match="correlation"):
        client.submit(ApprovedRealRunJob.model_validate(payload()))


def test_submit_rejects_approval_mismatch(tmp_path):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        request_body = json.loads(request.content)
        result = task()
        result["task"]["metadata"]["approval_id"] = "other-approval"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_body["id"], "result": result})

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError, match="approval"):
        client.submit(ApprovedRealRunJob.model_validate(payload()))


@pytest.mark.parametrize(
    "response_change,error_code",
    [
        ({"jsonrpc": "1.0"}, "invalid_response"),
        ({"id": "wrong-request-id"}, "invalid_response"),
    ],
)
def test_json_rpc_response_must_match_request(tmp_path, response_change, error_code):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        request_body = json.loads(request.content)
        response_body = {"jsonrpc": "2.0", "id": request_body["id"], "result": task()}
        response_body.update(response_change)
        return httpx.Response(200, json=response_body)

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError) as exc:
        client.status("task-1")
    assert exc.value.code == error_code


def test_lifecycle_values_are_validated_without_collapsing_them(tmp_path):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        request_body = json.loads(request.content)
        result = task()
        result["task"]["metadata"]["report_status"] = "unknown"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_body["id"], "result": result})

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError) as exc:
        client.status("task-1")
    assert exc.value.code == "invalid_lifecycle"


@pytest.mark.parametrize("metadata_change", [
    {"run_id": " "},
    {"context_id": 42},
    {"approval_id": None},
    {"iperf_run_ids": ["iperf-1", "iperf-1"]},
    {"artifact_sha256": "not-a-sha"},
    {"report_status": "completed"},
    {"ingest_status": "completed"},
])
def test_task_metadata_contract_is_strict(tmp_path, metadata_change):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        request_body = json.loads(request.content)
        result = task()
        result["task"]["metadata"].update(metadata_change)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_body["id"], "result": result})

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError):
        client.status("task-1")


def test_test_completion_requires_control_and_iperf_evidence(tmp_path):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        request_body = json.loads(request.content)
        result = task()
        result["task"]["metadata"]["test_status"] = "completed"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_body["id"], "result": result})

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError, match="execution evidence"):
        client.status("task-1")


def test_ingest_completion_requires_all_evidence(tmp_path):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        request_body = json.loads(request.content)
        result = task()
        result["task"]["metadata"].update({"test_status": "completed", "report_status": "completed", "ingest_status": "completed", "control_run_id": "control-1", "iperf_run_ids": ["iperf-1"], "artifact_sha256": "a" * 64})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_body["id"], "result": result})

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError, match="ingest"):
        client.status("task-1")


def test_wait_is_bounded_tasks_get_only_and_process_restart_safe(tmp_path):
    calls = []
    clock = {"now": 0.0}
    responses = [task(), task()]
    responses[1]["task"]["metadata"].update({"test_status": "completed", "report_status": "completed", "ingest_status": "completed", "control_run_id": "control-1", "iperf_run_ids": ["iperf-1"], "artifact_sha256": "a" * 64, "ingest_task_id": "ingest-1"})

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        body = json.loads(request.content)
        result = responses.pop(0)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    def sleeper(seconds):
        clock["now"] += seconds

    client, _ = setup_client(tmp_path, handler)
    result = client.wait("task-1", timeout_seconds=5, poll_interval_seconds=1, sleeper=sleeper, monotonic=lambda: clock["now"])
    assert result["metadata"]["ingest_status"] == "completed"
    assert [request.url.path for request in calls] == ["/.well-known/agent-card.json", "/a2a", "/a2a"]
    assert all(json.loads(request.content)["method"] == "tasks/get" for request in calls[1:])

    # status() is stateless: a fresh client can recover after process restart using only task-id.
    fresh_client, _ = setup_client(tmp_path, lambda request: httpx.Response(200, json=card()) if request.url.path.endswith("agent-card.json") else httpx.Response(200, json={"jsonrpc": "2.0", "id": json.loads(request.content)["id"], "result": task()}))
    assert fresh_client.status("task-1")["id"] == "task-1"


def test_wait_timeout_is_typed_without_real_sleep(tmp_path):
    clock = {"now": 0.0}
    rpc_calls = {"count": 0}

    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        rpc_calls["count"] += 1
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": task()})

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError) as exc:
        client.wait("task-1", timeout_seconds=1, poll_interval_seconds=1, sleeper=lambda seconds: clock.update(now=clock["now"] + seconds), monotonic=lambda: clock["now"])
    assert exc.value.code == "poll_timeout"
    assert rpc_calls["count"] == 1


@pytest.mark.parametrize("rpc_code,message,data,expected", [
    (-32602, "anything", {"secret": "secret-token"}, "invalid_real_run_contract"),
    (-32004, "task_not_running", {}, "task_not_running"),
    (-32004, "unstable", {"code": "unknown"}, "task_error"),
    (-32000, "busy", {}, "busy"),
    (-32000, "idempotency_conflict", {}, "idempotency_conflict"),
    (-32000, "cleanup_failed", {}, "cleanup_failed"),
])
def test_stable_rpc_error_mapping_is_typed_and_redacted(tmp_path, rpc_code, message, data, expected):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        request_body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": request_body["id"], "error": {"code": rpc_code, "message": message, "data": data}})

    client, _ = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError) as exc:
        client.status("task-1")
    assert exc.value.code == expected
    assert "secret-token" not in str(exc.value)


def test_disabled_gate_rejects_before_http_and_ca_is_required(tmp_path):
    client, calls = setup_client(tmp_path, lambda request: pytest.fail("HTTP must not be called"), enabled=False)
    with pytest.raises(RealRunDispatchUnavailable, match="disabled"):
        client.status("task-1")
    assert calls == []
    token = tmp_path / "token2"
    token.write_text("x", encoding="utf-8")
    token.chmod(0o600)
    with pytest.raises(RealRunDispatchUnavailable, match="CA trust"):
        RealRunClient(RealClientConfig(enabled=True, security_approved=True, endpoint="https://anritsu.example", token_file=token)).status("task-1")


def test_invalid_endpoint_port_and_task_identifier_fail_closed(tmp_path):
    client = RealRunClient(RealClientConfig(enabled=True, security_approved=True, endpoint="https://anritsu.example:bad"))
    with pytest.raises(RealRunDispatchUnavailable, match="valid HTTPS port"):
        client.status("task-1")
    with pytest.raises(ValueError, match="safe identifier"):
        RealRunClient().cancel("task\n1")


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://100.63.63.58:8792",
        "http://100.128.0.1:8792",
        "http://100.65.63.58:8791",
        "https://100.65.63.58:8792",
        "http://anritsu.example:8792",
        "http://[fd7a:115c:a1e0::1]:8792",
        "http://localhost:8792",
        "http://100.65.63.58:8792/a2a",
        "http://user@100.65.63.58:8792",
    ],
)
def test_tailscale_poc_rejects_non_literal_allowed_origin(tmp_path, endpoint):
    client, calls, _ = setup_poc_client(tmp_path, lambda request: pytest.fail("HTTP must not be called"), endpoint=endpoint)
    with pytest.raises(RealRunDispatchUnavailable):
        client.status("task-1")
    assert calls == []


@pytest.mark.parametrize(
    "expires_at",
    [
        datetime(2026, 8, 14, 12, tzinfo=timezone.utc),
        datetime(2026, 8, 14, 16, 0, 1, tzinfo=timezone.utc),
    ],
)
def test_tailscale_poc_requires_future_expiry_within_four_hours(tmp_path, expires_at):
    clock = lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc)
    client, calls, _ = setup_poc_client(tmp_path, lambda request: pytest.fail("HTTP must not be called"), expires_at=expires_at, now=clock)
    with pytest.raises(RealRunDispatchUnavailable, match="Tailscale HTTP POC"):
        client.status("task-1")
    assert calls == []


def test_tailscale_poc_requires_expiry_and_independent_token_file(tmp_path):
    client, calls, _ = setup_poc_client(tmp_path, lambda request: pytest.fail("HTTP must not be called"))
    client.config.tailscale_http_poc_expires_at = None
    with pytest.raises(RealRunDispatchUnavailable, match="expiry"):
        client.status("task-1")
    client.config.tailscale_http_poc_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    client.config.token_file = None
    with pytest.raises(RealRunDispatchUnavailable, match="token file"):
        client.status("task-1")
    assert calls == []


def test_tailscale_poc_valid_card_and_http_bearer(tmp_path):
    expiry = datetime(2026, 8, 14, 13, tzinfo=timezone.utc)
    clock = lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc)

    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=poc_card(expiry))
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": task()})

    client, calls, _ = setup_poc_client(tmp_path, handler, expires_at=expiry, now=clock)
    assert client.status("task-1")["id"] == "task-1"
    assert calls[0].url.scheme == "http"
    assert calls[0].headers["authorization"] == "Bearer secret-token"


@pytest.mark.parametrize("duration_seconds", [15, 30])
def test_tailscale_poc_submit_allows_only_bounded_first_job(tmp_path, duration_seconds):
    expiry = datetime(2026, 8, 14, 13, tzinfo=timezone.utc)
    clock = lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc)

    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=poc_card(expiry))
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": task()})

    client, calls, _ = setup_poc_client(tmp_path, handler, expires_at=expiry, now=clock)
    result = client.submit(ApprovedRealRunJob.model_validate(payload(duration_seconds=duration_seconds)))
    assert result["id"] == "task-1"
    assert len(calls) == 2


@pytest.mark.parametrize("change", [{"test_cases": ["sa_ul_tcp"]}, {"duration_seconds": 14}, {"duration_seconds": 31}])
def test_tailscale_poc_rejects_unbounded_first_job_before_http(tmp_path, change):
    client, calls, _ = setup_poc_client(tmp_path, lambda request: pytest.fail("HTTP must not be called"))
    job = ApprovedRealRunJob.model_validate(payload(**change))
    with pytest.raises(RealRunProtocolError, match="first job"):
        client.submit(job)
    assert calls == []


def test_tailscale_poc_ingest_disabled_completion_is_terminal(tmp_path):
    expiry = datetime(2026, 8, 14, 13, tzinfo=timezone.utc)
    completed = task()
    completed["task"]["metadata"].update(
        {
            "test_status": "completed",
            "report_status": "completed",
            "ingest_status": "not-started",
            "control_run_id": "control-1",
            "iperf_run_ids": ["iperf-1"],
            "artifact_sha256": "a" * 64,
        }
    )

    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=poc_card(expiry))
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": completed})

    client, calls, _ = setup_poc_client(tmp_path, handler, expires_at=expiry, now=lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc))
    result = client.wait("task-1", timeout_seconds=1, poll_interval_seconds=1, sleeper=lambda _: pytest.fail("wait must terminate"))
    assert result["metadata"]["ingest_status"] == "not-started"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "metadata_change",
    [
        {"artifact_sha256": None},
        {"test_status": "running"},
        {"report_status": "running"},
    ],
)
def test_tailscale_poc_ingest_disabled_completion_requires_evidence(tmp_path, metadata_change):
    expiry = datetime(2026, 8, 14, 13, tzinfo=timezone.utc)
    result = task()
    result["task"]["metadata"].update(
        {
            "test_status": "completed",
            "report_status": "completed",
            "ingest_status": "not-started",
            "control_run_id": "control-1",
            "iperf_run_ids": ["iperf-1"],
            "artifact_sha256": "a" * 64,
        }
    )
    result["task"]["metadata"].update(metadata_change)

    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=poc_card(expiry))
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    client, _, _ = setup_poc_client(tmp_path, handler, expires_at=expiry, now=lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc))
    with pytest.raises(RealRunProtocolError):
        client.status("task-1")


def test_https_rejects_ingest_disabled_not_started(tmp_path):
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=card())
        body = json.loads(request.content)
        result = task()
        result["task"]["metadata"]["ingest_status"] = "not-started"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": result})

    client, _, = setup_client(tmp_path, handler)
    with pytest.raises(RealRunProtocolError, match="lifecycle"):
        client.status("task-1")


@pytest.mark.parametrize(
    "change",
    [
        {"mode": "other"},
        {"tailnet_only": False},
        {"extra": True},
    ],
)
def test_tailscale_poc_requires_exact_card_extension(tmp_path, change):
    expiry = datetime(2026, 8, 14, 13, tzinfo=timezone.utc)
    def handler(request):
        value = poc_card(expiry)
        value["x-anritsu-transport"].update(change)
        return httpx.Response(200, json=value)

    client, _, _ = setup_poc_client(tmp_path, handler, expires_at=expiry, now=lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc))
    with pytest.raises(RealRunProtocolError, match="extension"):
        client.status("task-1")


def test_tailscale_poc_accepts_dotnet_seven_digit_raw_expiry(tmp_path):
    raw = "2026-08-14T13:24:47.7922157Z"
    expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=poc_card(expiry, **{"x-anritsu-transport": {"mode": "tailscale-http-poc", "tailnet_only": True, "expires_at": raw}}))
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": task()})
    client, _, _ = setup_poc_client(tmp_path, handler, expires_at=expiry, now=lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc))
    client.config.tailscale_http_poc_expires_at_raw = raw
    assert client.status("task-1")["id"] == "task-1"


def test_tailscale_poc_raw_card_string_mismatch_is_rejected(tmp_path):
    raw = "2026-08-14T13:24:47.7922157Z"
    expiry = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    def handler(request):
        return httpx.Response(200, json=poc_card(expiry))
    client, _, _ = setup_poc_client(tmp_path, handler, expires_at=expiry, now=lambda: datetime(2026, 8, 14, 12, tzinfo=timezone.utc))
    client.config.tailscale_http_poc_expires_at_raw = raw
    with pytest.raises(RealRunProtocolError, match="extension"):
        client.status("task-1")


def test_tailscale_poc_raw_and_parsed_expiry_mismatch_rejected():
    with pytest.raises(ValidationError, match="differs"):
        RealClientConfig(tailscale_http_poc_expires_at=datetime(2026, 8, 14, 13, tzinfo=timezone.utc), tailscale_http_poc_expires_at_raw="2026-08-14T13:24:47.7922157Z")


def test_tailscale_poc_from_env_preserves_raw_expiry(monkeypatch):
    raw = "2026-08-14T13:24:47.7922157Z"
    monkeypatch.setenv("KM_A2A_REAL_TAILSCALE_HTTP_POC_EXPIRES_AT", raw)
    config = RealClientConfig.from_env()
    assert config.tailscale_http_poc_expires_at_raw == raw
    assert config.tailscale_http_poc_expires_at == datetime.fromisoformat(raw.replace("Z", "+00:00"))


def test_tailscale_poc_expiry_blocks_cached_card_before_http(tmp_path):
    expiry = datetime(2026, 8, 14, 13, tzinfo=timezone.utc)
    current = {"value": datetime(2026, 8, 14, 12, tzinfo=timezone.utc)}

    def handler(request):
        if request.url.path.endswith("agent-card.json"):
            return httpx.Response(200, json=poc_card(expiry))
        body = json.loads(request.content)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": task()})

    client, calls, _ = setup_poc_client(tmp_path, handler, expires_at=expiry, now=lambda: current["value"])
    assert client.status("task-1")["id"] == "task-1"
    current["value"] = expiry
    with pytest.raises(RealRunDispatchUnavailable, match="expired"):
        client.status("task-1")
    assert len(calls) == 2


def test_cli_parameter_boundaries(tmp_path):
    job_file = tmp_path / "approved.json"
    job_file.write_text(json.dumps(payload()), encoding="utf-8")
    job_file.chmod(0o600)
    env = {**os.environ, "KM_A2A_REAL_ENABLED": "false"}
    root = Path(__file__).parents[1]
    status = subprocess.run([sys.executable, "scripts/km_anritsu_real_command.py", "status", "--task-id", "task-1"], cwd=root, env=env, capture_output=True, text=True)
    assert status.returncode == 1 and "disabled" in status.stderr
    rejected = subprocess.run([sys.executable, "scripts/km_anritsu_real_command.py", "status", "--approved-job-file", str(job_file)], cwd=root, env=env, capture_output=True, text=True)
    assert rejected.returncode == 2
    bounded = subprocess.run([sys.executable, "scripts/km_anritsu_real_command.py", "wait", "--task-id", "task-1", "--timeout", "301"], cwd=root, env=env, capture_output=True, text=True)
    assert bounded.returncode == 1 and "poll timeout" in bounded.stderr
