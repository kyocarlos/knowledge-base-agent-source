"""Official A2A SDK 1.0 client transport, currently exercised only against dry-run mocks."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import httpx
from google.protobuf.json_format import MessageToDict
from pydantic import SecretStr

from a2a.client import ClientConfig, ClientFactory
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers.proto_helpers import new_data_message
from a2a.types import Role, SendMessageRequest, TaskState

from .contracts import A2ATaskCorrelation, A2ATaskState, RejectionReason, RunStatus, TestJob
from .transport import TransportRejected, TransportResult


_STATE_MAP = {
    TaskState.TASK_STATE_SUBMITTED: A2ATaskState.SUBMITTED,
    TaskState.TASK_STATE_WORKING: A2ATaskState.WORKING,
    TaskState.TASK_STATE_COMPLETED: A2ATaskState.COMPLETED,
    TaskState.TASK_STATE_FAILED: A2ATaskState.FAILED,
    TaskState.TASK_STATE_CANCELED: A2ATaskState.CANCELED,
    TaskState.TASK_STATE_REJECTED: A2ATaskState.REJECTED,
}


class SdkA2ATransport:
    """Discover an Agent Card and submit one structured dry-run A2A message."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 15.0,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.http_transport = http_transport

    async def dispatch(self, endpoint: str, credential: SecretStr, job: TestJob) -> TransportResult:
        headers = {"Authorization": f"Bearer {credential.get_secret_value()}"}
        async with httpx.AsyncClient(
            headers=headers,
            timeout=self.timeout_seconds,
            transport=self.http_transport,
        ) as http_client:
            card = await A2ACardResolver(http_client, endpoint).get_agent_card()
            self._validate_card(endpoint, card)
            client = ClientFactory(
                ClientConfig(streaming=False, polling=True, httpx_client=http_client)
            ).create(card)
            try:
                request = SendMessageRequest(
                    message=new_data_message(
                        {
                            "job_schema_version": "1.0",
                            "dry_run": True,
                            **job.model_dump(),
                        },
                        media_type="application/json",
                        role=Role.ROLE_USER,
                    )
                )
                response = None
                async for event in client.send_message(request):
                    response = event
                    break
                if response is None or not response.HasField("task"):
                    raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent did not return an A2A Task")
                task = response.task
                if not task.id or not task.context_id:
                    raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent returned incomplete correlation")
                state = _STATE_MAP.get(task.status.state)
                if state is None:
                    raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent returned unsupported task state")
                metadata: dict[str, Any] = MessageToDict(task.metadata) if task.metadata.fields else {}
                if metadata.get("runId") not in {None, job.run_id}:
                    raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent returned mismatched run_id")
                if state is A2ATaskState.REJECTED:
                    reason_value = metadata.get("rejectionReason", RejectionReason.POLICY_DENIED.value)
                    try:
                        reason = RejectionReason(reason_value)
                    except ValueError:
                        reason = RejectionReason.POLICY_DENIED
                    raise TransportRejected(reason, "remote agent rejected the task")
                return TransportResult(
                    state=state,
                    correlation=A2ATaskCorrelation(
                        context_id=task.context_id,
                        a2a_task_id=task.id,
                        run_id=job.run_id,
                    ),
                    status=RunStatus(),
                )
            finally:
                await client.close()

    @staticmethod
    def _validate_card(endpoint: str, card) -> None:
        expected = urlsplit(endpoint)
        expected_origin = (expected.scheme.lower(), expected.hostname, expected.port or 443)
        if not card.supported_interfaces:
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "Agent Card has no interface")
        for interface in card.supported_interfaces:
            actual = urlsplit(interface.url)
            actual_origin = (actual.scheme.lower(), actual.hostname, actual.port or 443)
            if actual_origin != expected_origin:
                raise TransportRejected(RejectionReason.POLICY_DENIED, "Agent Card interface origin is not allowed")
        if not any(
            interface.protocol_binding == "JSONRPC" and interface.protocol_version.startswith("1.")
            for interface in card.supported_interfaces
        ):
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "Agent Card lacks A2A 1.x JSON-RPC")
        if not any(skill.id == "run_iperf_test" for skill in card.skills):
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "Agent Card lacks run_iperf_test skill")


__all__ = ["SdkA2ATransport"]
