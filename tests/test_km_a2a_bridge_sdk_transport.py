from __future__ import annotations

import asyncio

import httpx
import pytest
from google.protobuf.json_format import MessageToDict
from pydantic import SecretStr

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    SendMessageResponse,
    Task,
    TaskState,
    TaskStatus,
)

from km_a2a_bridge import A2ATaskState, RejectionReason, TestJob as JobContract
from km_a2a_bridge.config import BridgeConfig
from km_a2a_bridge.journal import TaskJournal
from km_a2a_bridge.sdk_transport import SdkA2ATransport
from km_a2a_bridge.service import BridgeService
from km_a2a_bridge.transport import TransportRejected


class MockAnritsuA2AServer:
    def __init__(self, state=TaskState.TASK_STATE_COMPLETED, metadata=None, interface_url="https://anritsu.test/a2a"):
        self.state = state
        self.metadata = metadata or {"runId": "run-wire-1"}
        self.interface_url = interface_url
        self.requests = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["authorization"] == "Bearer outbound-a2a-secret"
        if request.method == "GET":
            assert request.url.path == "/.well-known/agent-card.json"
            card = AgentCard(
                name="Mock Anritsu Agent",
                description="Wire contract test; no instrument access",
                supported_interfaces=[AgentInterface(
                    url=self.interface_url,
                    protocol_binding="JSONRPC",
                    protocol_version="1.0",
                )],
                version="1.0.0",
                capabilities=AgentCapabilities(streaming=False),
                default_input_modes=["application/json"],
                default_output_modes=["application/json"],
                skills=[AgentSkill(
                    id="run_iperf_test",
                    name="Dry-run iperf",
                    description="Validates a job without controlling an instrument",
                    input_modes=["application/json"],
                    output_modes=["application/json"],
                )],
            )
            return httpx.Response(200, json=MessageToDict(card))
        assert request.url.path == "/a2a"
        rpc = __import__("json").loads(request.content)
        assert rpc["jsonrpc"] == "2.0"
        assert rpc["method"] == "SendMessage"
        data = rpc["params"]["message"]["parts"][0]["data"]
        assert data["dry_run"] is True
        assert data["job_schema_version"] == "1.0"
        assert data["profile_id"] == "safe-profile"
        task = Task(
            id="a2a-task-wire-1",
            context_id="context-wire-1",
            status=TaskStatus(state=self.state),
            metadata=self.metadata,
        )
        result = MessageToDict(SendMessageResponse(task=task))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rpc["id"], "result": result})


def job():
    return JobContract(
        job_type="run_iperf_test",
        environment="anritsu",
        profile_id="safe-profile",
        run_id="run-wire-1",
        requested_by="operator-1",
        duration_seconds=60,
        test_cases=["sa_dl_tcp"],
    )


def dispatch(server):
    transport = SdkA2ATransport(http_transport=httpx.MockTransport(server))
    return asyncio.run(transport.dispatch(
        "https://anritsu.test", SecretStr("outbound-a2a-secret"), job()
    ))


def test_official_sdk_discovers_card_and_sends_structured_dry_run_task():
    server = MockAnritsuA2AServer()
    result = dispatch(server)
    assert result.state is A2ATaskState.COMPLETED
    assert result.correlation.context_id == "context-wire-1"
    assert result.correlation.a2a_task_id == "a2a-task-wire-1"
    assert result.correlation.run_id == "run-wire-1"
    assert [request.method for request in server.requests] == ["GET", "POST"]


def test_remote_rejection_maps_to_stable_reason():
    server = MockAnritsuA2AServer(
        state=TaskState.TASK_STATE_REJECTED,
        metadata={"runId": "run-wire-1", "rejectionReason": "busy"},
    )
    with pytest.raises(TransportRejected) as caught:
        dispatch(server)
    assert caught.value.reason is RejectionReason.BUSY
    assert "outbound-a2a-secret" not in str(caught.value)


def test_mismatched_run_id_is_rejected():
    server = MockAnritsuA2AServer(metadata={"runId": "different-run"})
    with pytest.raises(TransportRejected) as caught:
        dispatch(server)
    assert caught.value.reason is RejectionReason.INVALID_REQUEST


def test_agent_card_cannot_redirect_bearer_credential_to_another_origin():
    server = MockAnritsuA2AServer(interface_url="https://evil.example/a2a")
    with pytest.raises(TransportRejected) as caught:
        dispatch(server)
    assert caught.value.reason is RejectionReason.POLICY_DENIED
    assert [request.method for request in server.requests] == ["GET"]


def test_sdk_dry_run_persists_wire_correlation_through_bridge_service(tmp_path):
    server = MockAnritsuA2AServer()
    config = BridgeConfig(
        enabled=True,
        transport_mode="sdk-dry-run",
        control_token_sha256="a" * 64,
        allowed_profiles={"anritsu": {"safe-profile"}},
        agent_endpoints={"anritsu": "https://anritsu.test"},
        agent_credentials={"anritsu": "outbound-a2a-secret"},
        journal_path=tmp_path / "tasks.sqlite3",
    )
    journal = TaskJournal(config.journal_path)
    service = BridgeService(
        config,
        journal,
        SdkA2ATransport(http_transport=httpx.MockTransport(server)),
    )
    record, duplicate = asyncio.run(service.submit(job()))
    assert duplicate is False
    assert record.state is A2ATaskState.COMPLETED
    assert record.correlation.context_id == "context-wire-1"
    assert journal.get("anritsu:run-wire-1") == record
