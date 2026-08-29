"""Official A2A SDK 1.0 client transport, currently exercised only against dry-run mocks."""

from __future__ import annotations

from typing import Any
import os
from uuid import uuid4
from urllib.parse import urlsplit

import httpx
from google.protobuf.json_format import MessageToDict, ParseDict
from pydantic import SecretStr

from a2a.client import ClientConfig, ClientFactory
from a2a.client.card_resolver import A2ACardResolver
from a2a.helpers.proto_helpers import new_data_message
from a2a.types import Role, SendMessageRequest, TaskState
from a2a.types import Task
from a2a.utils.errors import InvalidParamsError

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
        timeout_seconds: float | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else float(os.getenv("KM_A2A_HTTP_TIMEOUT_SECONDS", "60"))
        self.http_transport = http_transport

    async def dispatch(self, endpoint: str, credential: SecretStr, job: TestJob) -> TransportResult:
        headers = {
            "Authorization": f"Bearer {credential.get_secret_value()}",
            "A2A-Version": "1.0",
        }
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
                try:
                    task = await self._send_with_sdk(client, job)
                except InvalidParamsError:
                    # A2A SDK 1.1.2 emits the operation name ``SendMessage``.
                    # This POC peer follows the JSON-RPC 1.0 wire name
                    # ``message/send`` documented by the integration contract.
                    task = await self._send_message_send(
                        http_client,
                        next(
                            interface.url
                            for interface in card.supported_interfaces
                            if interface.protocol_binding == "JSONRPC"
                            and interface.protocol_version.startswith("1.")
                        ),
                        headers,
                        job,
                    )
                if not task.id or not task.context_id:
                    raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent returned incomplete correlation")
                state = _STATE_MAP.get(task.status.state)
                if state is None:
                    raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent returned unsupported task state")
                metadata: dict[str, Any] = MessageToDict(task.metadata) if task.metadata.fields else {}
                run_id = metadata.get("run_id", metadata.get("runId"))
                if run_id != job.run_id:
                    raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent returned mismatched run_id")
                if state is A2ATaskState.REJECTED:
                    reason_value = metadata.get("rejectionReason", RejectionReason.POLICY_DENIED.value)
                    try:
                        reason = RejectionReason(reason_value)
                    except ValueError:
                        reason = RejectionReason.POLICY_DENIED
                    raise TransportRejected(reason, "remote agent rejected the task")
                if state is A2ATaskState.COMPLETED:
                    self._validate_dry_run_metadata(metadata, task.id, task.context_id)
                return TransportResult(
                    state=state,
                    correlation=A2ATaskCorrelation(
                        context_id=task.context_id,
                        a2a_task_id=task.id,
                        run_id=job.run_id,
                        openclaw_forward_status=self._metadata_value(metadata, "openclaw_forward_status", "openclawForwardStatus"),
                        openclaw_receiver=self._metadata_value(metadata, "openclaw_receiver", "openclawReceiver"),
                        openclaw_audit_id=self._metadata_value(metadata, "openclaw_audit_id", "openclawAuditId"),
                        dry_run_side_effect_counts=self._zero_side_effect_counts(metadata),
                    ),
                    status=RunStatus(),
                )
            finally:
                await client.close()

    @staticmethod
    async def _send_with_sdk(client, job: TestJob):
        request = SendMessageRequest(
            message=new_data_message(
                {**job.model_dump()},
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
        return response.task

    @staticmethod
    async def _send_message_send(http_client, interface_url, headers, job: TestJob) -> Task:
        response = await http_client.post(
            interface_url,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": str(uuid4()),
                "method": "message/send",
                "params": {
                    "message": {
                        "messageId": f"msg-{uuid4().hex}",
                        "role": "ROLE_USER",
                        "parts": [{"data": job.model_dump()}],
                    }
                },
            },
        )
        response.raise_for_status()
        body = response.json()
        result = body.get("result")
        task_data = result.get("task") if isinstance(result, dict) else None
        if not isinstance(task_data, dict):
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent did not return an A2A Task")
        return ParseDict(task_data, Task())

    @staticmethod
    def _validate_card(endpoint: str, card) -> None:
        expected = urlsplit(endpoint)
        expected_origin = (expected.scheme.lower(), expected.hostname, expected.port or (80 if expected.scheme.lower() == "http" else 443))
        if not card.supported_interfaces:
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "Agent Card has no interface")
        for interface in card.supported_interfaces:
            actual = urlsplit(interface.url)
            actual_origin = (actual.scheme.lower(), actual.hostname, actual.port or (80 if actual.scheme.lower() == "http" else 443))
            if actual_origin != expected_origin:
                raise TransportRejected(RejectionReason.POLICY_DENIED, "Agent Card interface origin is not allowed")
        if not any(
            interface.protocol_binding == "JSONRPC" and interface.protocol_version.startswith("1.")
            for interface in card.supported_interfaces
        ):
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "Agent Card lacks A2A 1.x JSON-RPC")
        if not any(skill.id == "run_iperf_test" for skill in card.skills):
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "Agent Card lacks run_iperf_test skill")

    @staticmethod
    def _metadata_value(metadata: dict[str, Any], snake: str, camel: str) -> str | None:
        value = metadata.get(snake, metadata.get(camel))
        return value if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _zero_side_effect_counts(metadata: dict[str, Any]) -> dict[str, int]:
        counts = metadata.get("dry_run_side_effect_counts", metadata.get("dryRunSideEffectCounts", {}))
        return {str(key): int(value) for key, value in counts.items()} if isinstance(counts, dict) else {}

    @staticmethod
    def _validate_dry_run_metadata(metadata: dict[str, Any], task_id: str, context_id: str) -> None:
        def value(snake: str, camel: str):
            return metadata.get(snake, metadata.get(camel))

        expected = {
            "context_id": context_id,
            "a2a_task_id": task_id,
            "test_status": "pending",
            "report_status": "pending",
            "ingest_status": "pending",
        }
        for key, expected_value in expected.items():
            camel = key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:])
            if value(key, camel) != expected_value:
                raise TransportRejected(RejectionReason.INVALID_REQUEST, f"agent returned invalid dry-run {key}")
        receiver_expectations = {
            "openclaw_forward_status": "accepted",
            "openclaw_receiver": "anritsu-openclaw",
        }
        for key, expected_value in receiver_expectations.items():
            camel = key.split("_")[0] + "".join(part.title() for part in key.split("_")[1:])
            if value(key, camel) != expected_value:
                raise TransportRejected(RejectionReason.INVALID_REQUEST, f"agent returned invalid {key}")
        audit_id = value("openclaw_audit_id", "openclawAuditId")
        if not isinstance(audit_id, str) or not audit_id.strip():
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "agent did not return openclaw_audit_id")
        counts = value("dry_run_side_effect_counts", "dryRunSideEffectCounts")
        if not isinstance(counts, dict) or len(counts) != 7 or any(not isinstance(v, (int, float)) or v != 0 for v in counts.values()):
            raise TransportRejected(RejectionReason.INVALID_REQUEST, "dry-run side effects were not proven zero")


__all__ = ["SdkA2ATransport"]
