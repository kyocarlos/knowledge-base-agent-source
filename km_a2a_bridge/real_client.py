"""Independent, disabled-by-default A2A real-run JSON-RPC client."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
_CASES = frozenset({"sa_dl_tcp", "sa_ul_tcp"})
_POC_FIRST_CASE = "sa_dl_tcp"
_POC_DURATION_SECONDS = (15, 30)
_FIRST_REAL_CASE = "sa_dl_tcp"
_FIRST_REAL_DURATION_SECONDS = 15
_METHOD_SCOPES = {
    "message/send": "real:test:run",
    "tasks/get": "real:test:status",
    "tasks/cancel": "real:test:cancel",
}
_RPC_CODES = {-32700: "parse_error", -32600: "invalid_request", -32601: "method_not_found", -32602: "invalid_real_run_contract", -32001: "authentication", -32020: "real_run_gate_closed"}
_LIFECYCLE_STATUSES = frozenset({"pending", "running", "completed", "failed", "canceled"})
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_POLL_INTERVAL = (0.1, 60.0)
_POLL_TIMEOUT = (1.0, 300.0)


class ApprovedRealRunJob(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    job_schema_version: Literal["1.1-real-no-approval"]
    dry_run: Literal[False]
    job_type: Literal["run_iperf_test"]
    environment: Literal["anritsu"]
    profile_id: Literal["ncq2200b2v-throughput-v1"]
    run_id: str
    requested_by: str
    duration_seconds: StrictInt = Field(ge=1, le=3600)
    test_cases: list[str] = Field(min_length=1, max_length=1)

    @field_validator("run_id", "requested_by")
    @classmethod
    def _safe_identifier(cls, value: str) -> str:
        if not _SAFE_IDENTIFIER.fullmatch(value):
            raise ValueError("must use a safe identifier")
        return value

    @field_validator("test_cases")
    @classmethod
    def _one_allowlisted_case(cls, values: list[str]) -> list[str]:
        if len(values) != 1 or values[0] not in _CASES:
            raise ValueError("exactly one allowlisted Anritsu test case is required")
        return values


class RealClientConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    security_approved: bool = False
    tailscale_http_poc: bool = False
    tailscale_http_poc_expires_at: datetime | None = None
    tailscale_http_poc_expires_at_raw: str | None = None
    endpoint: str | None = None
    token_file: Path | None = None
    ca_file: Path | None = None
    client_cert_file: Path | None = None
    client_key_file: Path | None = None
    first_test_lockdown: bool = True
    ingest_enabled: bool = False
    timeout_seconds: StrictInt = Field(default=60, ge=1, le=3600)
    poll_interval_seconds: float = Field(default=1.0, strict=True, ge=_POLL_INTERVAL[0], le=_POLL_INTERVAL[1])
    poll_timeout_seconds: float = Field(default=300.0, strict=True, ge=_POLL_TIMEOUT[0], le=_POLL_TIMEOUT[1])

    @model_validator(mode="after")
    def _validate_expiry_raw(self) -> "RealClientConfig":
        if self.tailscale_http_poc_expires_at_raw is None:
            return self
        try:
            parsed = datetime.fromisoformat(self.tailscale_http_poc_expires_at_raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("tailscale HTTP POC expiry raw value must be ISO8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("tailscale HTTP POC expiry raw value must be timezone-aware")
        if self.tailscale_http_poc_expires_at is None:
            self.tailscale_http_poc_expires_at = parsed
        elif self.tailscale_http_poc_expires_at != parsed:
            raise ValueError("tailscale HTTP POC expiry raw value differs from parsed expiry")
        return self

    @classmethod
    def from_env(cls) -> "RealClientConfig":
        return cls(
            enabled=_env_bool("KM_A2A_REAL_ENABLED"),
            security_approved=_env_bool("KM_A2A_REAL_SECURITY_APPROVED"),
            tailscale_http_poc=_env_bool("KM_A2A_REAL_TAILSCALE_HTTP_POC"),
            tailscale_http_poc_expires_at=_env_datetime("KM_A2A_REAL_TAILSCALE_HTTP_POC_EXPIRES_AT"),
            tailscale_http_poc_expires_at_raw=os.getenv("KM_A2A_REAL_TAILSCALE_HTTP_POC_EXPIRES_AT") or None,
            endpoint=os.getenv("KM_A2A_REAL_ENDPOINT") or None,
            token_file=Path(os.environ["KM_A2A_REAL_TOKEN_FILE"]) if os.getenv("KM_A2A_REAL_TOKEN_FILE") else None,
            ca_file=Path(os.environ["KM_A2A_REAL_CA_FILE"]) if os.getenv("KM_A2A_REAL_CA_FILE") else None,
            client_cert_file=Path(os.environ["KM_A2A_REAL_CLIENT_CERT_FILE"]) if os.getenv("KM_A2A_REAL_CLIENT_CERT_FILE") else None,
            client_key_file=Path(os.environ["KM_A2A_REAL_CLIENT_KEY_FILE"]) if os.getenv("KM_A2A_REAL_CLIENT_KEY_FILE") else None,
            first_test_lockdown=_env_bool("KM_A2A_REAL_FIRST_TEST_LOCKDOWN"),
            ingest_enabled=_env_bool("KM_A2A_REAL_KM_INGEST_ENABLED"),
            timeout_seconds=int(os.getenv("KM_A2A_REAL_HTTP_TIMEOUT_SECONDS", "60")),
            poll_interval_seconds=float(os.getenv("KM_A2A_REAL_POLL_INTERVAL_SECONDS", "1")),
            poll_timeout_seconds=float(os.getenv("KM_A2A_REAL_POLL_TIMEOUT_SECONDS", "300")),
        )


class RealRunDispatchUnavailable(RuntimeError):
    """The local gate prevents dispatch (including the disabled default)."""


class RealRunProtocolError(RuntimeError):
    """A stable, secret-free protocol or HTTP error."""

    def __init__(self, code: str, message: str, *, status_code: int | None = None):
        self.code, self.status_code = code, status_code
        super().__init__(message)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def agent_card_digest(card: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(card)).hexdigest()


class RealRunClient:
    def __init__(
        self,
        config: RealClientConfig | None = None,
        *,
        http_transport: httpx.BaseTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.config = config or RealClientConfig.from_env()
        self.http_transport = http_transport
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._card: dict[str, Any] | None = None
        self._card_digest: str | None = None

    @property
    def card_evidence(self) -> dict[str, str] | None:
        """Safe evidence suitable for logging; it never contains credentials."""
        if self._card is None or self._card_digest is None:
            return None
        return {"endpoint": self.config.endpoint or "", "version": str(self._card.get("version", "")), "digest": self._card_digest}

    @staticmethod
    def load_approved_job(path: Path) -> ApprovedRealRunJob:
        if path.is_symlink() or not path.is_file():
            raise ValueError("approved job file must be a regular non-symlink file")
        try:
            if stat.S_IMODE(path.stat().st_mode) != 0o600:
                raise ValueError("approved job file must have mode 0600")
            return ApprovedRealRunJob.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError) as exc:
            raise ValueError("cannot read approved job file") from exc

    def prepare(self, job: ApprovedRealRunJob) -> dict[str, object]:
        return job.model_dump(mode="json")

    def _network_gate(self) -> str:
        if not self.config.enabled:
            return "real-run client is disabled"
        if not self.config.security_approved:
            return "real-run security approval is required"
        parsed = urlsplit(self.config.endpoint or "")
        try:
            parsed.port
        except ValueError:
            return "real-run endpoint must use a valid HTTPS port"
        if parsed.username or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            return "real-run endpoint must not contain path, query, fragment, or userinfo"
        if self.config.first_test_lockdown and self.config.ingest_enabled:
            return "first real test requires KM ingest to remain disabled"
        if self.config.tailscale_http_poc:
            if parsed.scheme.lower() != "http" or parsed.port != 8792 or not _is_tailscale_ipv4(parsed.hostname):
                return "Tailscale HTTP POC endpoint must be a literal 100.64.0.0/10 IPv4 address on port 8792"
            expires_at = self.config.tailscale_http_poc_expires_at
            try:
                current = _aware_utc(self._now())
            except (TypeError, ValueError):
                return "Tailscale HTTP POC clock must return a timezone-aware datetime"
            if expires_at is None or expires_at.tzinfo is None:
                return "Tailscale HTTP POC expiry must be timezone-aware"
            expiry = expires_at.astimezone(timezone.utc)
            if expiry <= current:
                return "Tailscale HTTP POC has expired"
            if expiry > current + timedelta(hours=4):
                return "Tailscale HTTP POC expiry must be within 4 hours"
        elif parsed.scheme.lower() != "https":
            return "real-run endpoint must be HTTPS without a path, query, or fragment"
        files = [(self.config.token_file, "token"), (self.config.client_cert_file, "client certificate"), (self.config.client_key_file, "client key")]
        if not self.config.tailscale_http_poc:
            files.append((self.config.ca_file, "CA trust"))
        for path, label in files:
            if path is None:
                return f"real-run {label} file is required"
            if path.is_symlink() or not path.is_file():
                return f"real-run {label} file must be a regular non-symlink file"
            try:
                if label in {"token", "client key"} and stat.S_IMODE(path.stat().st_mode) != 0o600:
                    return "real-run token file must have mode 0600"
                if not path.read_bytes():
                    return f"real-run {label} file must not be empty"
            except (OSError, UnicodeError):
                return f"real-run {label} file cannot be read"
        return ""

    def _gate(self) -> None:
        if (reason := self._network_gate()):
            raise RealRunDispatchUnavailable(reason)

    def _origin(self) -> tuple[str, str, int]:
        parsed = urlsplit(self.config.endpoint or "")
        return parsed.scheme.lower(), parsed.hostname or "", parsed.port or (8792 if self.config.tailscale_http_poc else 443)

    def _client(self) -> httpx.Client:
        # POC relies on WireGuard transport; httpx keeps its safe default TLS
        # verification setting and never disables certificate verification.
        verify: bool | str = True if self.config.tailscale_http_poc else str(self.config.ca_file)
        cert = None
        if not self.config.tailscale_http_poc:
            cert = (str(self.config.client_cert_file), str(self.config.client_key_file))
        return httpx.Client(base_url=self.config.endpoint, timeout=self.config.timeout_seconds, verify=verify, cert=cert, transport=self.http_transport)

    def _token(self) -> str:
        try:
            token = self.config.token_file.read_text(encoding="utf-8").strip()  # type: ignore[union-attr]
        except (OSError, UnicodeError) as exc:
            raise RealRunDispatchUnavailable("real-run token file cannot be read") from exc
        if not token:
            raise RealRunDispatchUnavailable("real-run token file must not be empty")
        return token

    def _ensure_card(self, client: httpx.Client, token: str) -> None:
        if self._card is not None:
            return
        try:
            response = client.get("/.well-known/agent-card.json", headers={"Authorization": f"Bearer {token}", "A2A-Version": "1.0"})
        except httpx.HTTPError as exc:
            raise RealRunProtocolError("transport_error", "real-run request failed") from exc
        self._raise_http(response)
        try:
            card = response.json()
        except ValueError as exc:
            raise RealRunProtocolError("invalid_agent_card", "Agent Card is not JSON") from exc
        self._validate_card(card)
        self._card = card
        self._card_digest = agent_card_digest(card)

    def _validate_card(self, card: Any) -> None:
        if not isinstance(card, dict) or card.get("version") != "1.1-real-no-approval":
            raise RealRunProtocolError("invalid_agent_card", "Agent Card version is not 1.1-real-no-approval")
        if _contains_sensitive_key(card):
            raise RealRunProtocolError("invalid_agent_card", "Agent Card contains a prohibited sensitive field")
        interfaces = card.get("supportedInterfaces")
        if not isinstance(interfaces, list) or not interfaces:
            raise RealRunProtocolError("invalid_agent_card", "Agent Card has no supported interfaces")
        origin = self._origin()
        for interface in interfaces:
            if not isinstance(interface, dict):
                raise RealRunProtocolError("invalid_agent_card", "Agent Card interface is invalid")
            parsed = urlsplit(str(interface.get("url", "")))
            try:
                port = parsed.port
            except ValueError as exc:
                raise RealRunProtocolError("invalid_agent_card", "Agent Card interface port is invalid") from exc
            actual = (parsed.scheme.lower(), parsed.hostname or "", port or (443 if parsed.scheme.lower() == "https" else 80))
            if actual != origin or parsed.username or parsed.password or parsed.path != "/a2a" or parsed.query or parsed.fragment:
                raise RealRunProtocolError("invalid_agent_card", "Agent Card interface origin or path is not allowed")
        if not any(i.get("protocolBinding") == "JSONRPC" and i.get("protocolVersion") == "1.0" for i in interfaces if isinstance(i, dict)):
            raise RealRunProtocolError("invalid_agent_card", "Agent Card lacks JSON-RPC protocol version 1.0")
        skills = card.get("skills")
        if not isinstance(skills, list) or len(skills) != 1 or not isinstance(skills[0], dict) or skills[0].get("id") != "run_iperf_test_real":
            raise RealRunProtocolError("invalid_agent_card", "Agent Card skills are not allowlisted")
        security_schemes = card.get("securitySchemes")
        bearer_names = {name for name, scheme in security_schemes.items() if _contains_bearer_scheme(scheme)} if isinstance(security_schemes, dict) else set()
        requirements = card.get("securityRequirements")
        referenced_names = {name for requirement in requirements if isinstance(requirement, dict) and isinstance(requirement.get("schemes"), dict) for name in requirement["schemes"]} if isinstance(requirements, list) else set()
        if not bearer_names or not bearer_names.intersection(referenced_names):
            raise RealRunProtocolError("invalid_agent_card", "Agent Card lacks Bearer security declaration")
        if self.config.tailscale_http_poc:
            expected = {
                "mode": "tailscale-http-poc",
                "tailnet_only": True,
                "expires_at": self.config.tailscale_http_poc_expires_at_raw or (self.config.tailscale_http_poc_expires_at.isoformat() if self.config.tailscale_http_poc_expires_at else None),
            }
            if card.get("x-anritsu-transport") != expected:
                raise RealRunProtocolError("invalid_agent_card", "Agent Card Tailscale transport extension is invalid")

    @staticmethod
    def _raise_http(response: httpx.Response) -> None:
        if response.status_code in (401, 403, 503):
            code = {401: "authentication_required", 403: "forbidden", 503: "real_run_gate_closed"}[response.status_code]
            raise RealRunProtocolError(code, {401: "authentication failed", 403: "permission denied", 503: "real-run gate is closed"}[response.status_code], status_code=response.status_code)
        if response.status_code >= 400:
            raise RealRunProtocolError("http_error", "real-run HTTP request failed", status_code=response.status_code)

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._gate()
        token = self._token()
        with self._client() as client:
            self._ensure_card(client, token)
            request_id = str(uuid4())
            body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            try:
                response = client.post("/a2a", headers={"Authorization": f"Bearer {token}", "A2A-Version": "1.0", "Content-Type": "application/json"}, json=body)
            except httpx.HTTPError as exc:
                raise RealRunProtocolError("transport_error", "real-run request failed") from exc
            self._raise_http(response)
            try:
                envelope = response.json()
            except ValueError as exc:
                raise RealRunProtocolError("invalid_response", "real-run response is not JSON") from exc
            if (
                not isinstance(envelope, dict)
                or set(envelope) - {"jsonrpc", "id", "result", "error"}
                or envelope.get("jsonrpc") != "2.0"
                or envelope.get("id") != request_id
                or (("result" in envelope) == ("error" in envelope))
            ):
                raise RealRunProtocolError("invalid_response", "invalid JSON-RPC response")
            if "error" in envelope:
                error = envelope["error"] if isinstance(envelope["error"], dict) else {}
                raw_code = error.get("code", "rpc_error")
                code = _rpc_error_code(raw_code, error.get("message"), error.get("data"))
                raise RealRunProtocolError(code, "remote JSON-RPC request failed")
            result = envelope.get("result")
            if not isinstance(result, dict):
                raise RealRunProtocolError("invalid_response", "JSON-RPC result is invalid")
            return result

    def _validate_task(self, result: dict[str, Any], *, expected_run_id: str | None = None, expected_task_id: str | None = None) -> dict[str, Any]:
        task = result.get("task", result)
        if not isinstance(task, dict) or not isinstance(task.get("id"), str) or not task["id"].strip() or not isinstance(task.get("contextId"), str) or not task["contextId"].strip():
            raise RealRunProtocolError("invalid_correlation", "task correlation is incomplete")
        metadata = task.get("metadata")
        if not isinstance(metadata, dict):
            raise RealRunProtocolError("invalid_correlation", "task metadata is missing")
        for key in ("run_id", "context_id", "a2a_task_id"):
            if not isinstance(metadata.get(key), str) or not metadata[key].strip():
                raise RealRunProtocolError("invalid_correlation", "task metadata is incomplete")
            if not _SAFE_IDENTIFIER.fullmatch(metadata[key]):
                raise RealRunProtocolError("invalid_correlation", "task metadata is invalid")
        for key in ("test_status", "report_status"):
            if metadata.get(key) not in _LIFECYCLE_STATUSES:
                raise RealRunProtocolError("invalid_lifecycle", "task lifecycle status is invalid")
        ingest_status = metadata.get("ingest_status")
        if ingest_status not in _LIFECYCLE_STATUSES and not (self.config.tailscale_http_poc and ingest_status == "not-started"):
            raise RealRunProtocolError("invalid_lifecycle", "task lifecycle status is invalid")
        for key in ("control_run_id", "real_run_audit_id", "ingest_task_id"):
            if key in metadata and (not isinstance(metadata[key], str) or not _SAFE_IDENTIFIER.fullmatch(metadata[key])):
                raise RealRunProtocolError("invalid_correlation", "task metadata is invalid")
        if "iperf_run_ids" in metadata:
            values = metadata["iperf_run_ids"]
            if not isinstance(values, list) or any(not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value) for value in values) or len(values) != len(set(values)):
                raise RealRunProtocolError("invalid_correlation", "task metadata is invalid")
        if "artifact_sha256" in metadata and (not isinstance(metadata["artifact_sha256"], str) or not _SHA256.fullmatch(metadata["artifact_sha256"])):
            raise RealRunProtocolError("invalid_correlation", "task metadata is invalid")
        if metadata["report_status"] == "completed" and "artifact_sha256" not in metadata:
            raise RealRunProtocolError("invalid_lifecycle", "report completion lacks artifact")
        if metadata["test_status"] == "completed" and (
            "control_run_id" not in metadata
            or "iperf_run_ids" not in metadata
            or not metadata["iperf_run_ids"]
        ):
            raise RealRunProtocolError("invalid_lifecycle", "test completion lacks execution evidence")
        if metadata["report_status"] == "completed" and metadata["test_status"] != "completed":
            raise RealRunProtocolError("invalid_lifecycle", "report completion lacks completed test")
        if metadata["ingest_status"] == "completed" and (
            metadata["test_status"] != "completed"
            or metadata["report_status"] != "completed"
            or "artifact_sha256" not in metadata
            or "ingest_task_id" not in metadata
        ):
            raise RealRunProtocolError("invalid_lifecycle", "ingest completion is incomplete")
        if metadata["ingest_status"] == "not-started" and (
            self.config.ingest_enabled
            or metadata["test_status"] != "completed"
            or metadata["report_status"] != "completed"
            or "artifact_sha256" not in metadata
        ):
            raise RealRunProtocolError("invalid_lifecycle", "POC ingest-disabled completion is incomplete")
        if (expected_task_id is not None and task["id"] != expected_task_id) or metadata["context_id"] != task["contextId"] or metadata["a2a_task_id"] != task["id"] or (expected_run_id is not None and metadata["run_id"] != expected_run_id):
            raise RealRunProtocolError("correlation_mismatch", "task correlation does not match response")
        return task

    def submit(self, job: ApprovedRealRunJob) -> dict[str, Any]:
        if self.config.first_test_lockdown and (
            job.test_cases != [_FIRST_REAL_CASE] or job.duration_seconds != _FIRST_REAL_DURATION_SECONDS
        ):
            raise RealRunProtocolError("first_test_lockdown", "first real test is fixed to sa_dl_tcp for 15 seconds")
        if self.config.tailscale_http_poc and (
            job.test_cases != [_POC_FIRST_CASE]
            or not _POC_DURATION_SECONDS[0] <= job.duration_seconds <= _POC_DURATION_SECONDS[1]
        ):
            raise RealRunProtocolError("invalid_real_run_contract", "Tailscale HTTP POC first job must be sa_dl_tcp for 15-30 seconds")
        result = self._rpc("message/send", {"message": {"messageId": f"msg-{uuid4().hex}", "role": "ROLE_USER", "parts": [{"data": self.prepare(job)}]}})
        task = self._validate_task(result, expected_run_id=job.run_id)
        return task

    def status(self, task_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or not _SAFE_IDENTIFIER.fullmatch(task_id):
            raise ValueError("task id must use a safe identifier")
        return self._validate_task(self._rpc("tasks/get", {"id": task_id}), expected_task_id=task_id)

    def cancel(self, task_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or not _SAFE_IDENTIFIER.fullmatch(task_id):
            raise ValueError("task id must use a safe identifier")
        return self._validate_task(self._rpc("tasks/cancel", {"id": task_id}), expected_task_id=task_id)

    def wait(
        self,
        task_id: str,
        *,
        timeout_seconds: float | None = None,
        poll_interval_seconds: float | None = None,
        sleeper: Any = time.sleep,
        monotonic: Any = time.monotonic,
    ) -> dict[str, Any]:
        timeout = self.config.poll_timeout_seconds if timeout_seconds is None else timeout_seconds
        interval = self.config.poll_interval_seconds if poll_interval_seconds is None else poll_interval_seconds
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not _POLL_TIMEOUT[0] <= timeout <= _POLL_TIMEOUT[1]:
            raise ValueError("poll timeout must be within configured bounds")
        if not isinstance(interval, (int, float)) or isinstance(interval, bool) or not _POLL_INTERVAL[0] <= interval <= _POLL_INTERVAL[1]:
            raise ValueError("poll interval must be within configured bounds")
        started = monotonic()
        first_attempt = True
        while True:
            if not first_attempt and monotonic() - started >= timeout:
                raise RealRunProtocolError("poll_timeout", "real-run task polling timed out")
            first_attempt = False
            task = self.status(task_id)
            metadata = task["metadata"]
            if (
                metadata["ingest_status"] == "completed"
                or (self.config.tailscale_http_poc and metadata["ingest_status"] == "not-started")
                or any(metadata[key] in {"failed", "canceled"} for key in ("test_status", "report_status", "ingest_status"))
            ):
                return task
            remaining = timeout - (monotonic() - started)
            if remaining <= 0:
                raise RealRunProtocolError("poll_timeout", "real-run task polling timed out")
            sleeper(min(interval, remaining))


def _env_bool(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _env_datetime(name: str) -> datetime | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO8601") from exc


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


def _is_tailscale_ipv4(hostname: str | None) -> bool:
    if not hostname:
        return False
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return False
    return isinstance(address, ipaddress.IPv4Address) and address in ipaddress.ip_network("100.64.0.0/10")


def _rpc_error_code(raw_code: Any, message: Any, data: Any) -> str:
    if raw_code == -32004:
        stable = _stable_remote_value(message, data)
        return stable if stable in {"task_not_found", "task_not_running"} else "task_error"
    stable = _stable_remote_value(message, data)
    if stable in {"busy", "idempotency_conflict", "cleanup_failed"}:
        return stable
    return _RPC_CODES.get(raw_code, f"rpc_{raw_code}")


def _stable_remote_value(message: Any, data: Any) -> str | None:
    values: list[Any] = [message]
    if isinstance(data, dict):
        values.extend(data.values())
    else:
        values.append(data)
    return next((value for value in values if isinstance(value, str) and value in {"task_not_found", "task_not_running", "busy", "idempotency_conflict", "cleanup_failed"}), None)


def _contains_bearer_scheme(value: Any) -> bool:
    if isinstance(value, dict):
        scheme = value.get("scheme")
        if isinstance(scheme, str) and scheme.lower() == "bearer":
            return True
        return any(_contains_bearer_scheme(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_bearer_scheme(child) for child in value)
    return False


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        prohibited = {"authorization", "password", "secret", "token"}
        if any(str(key).lower() in prohibited for key in value):
            return True
        return any(_contains_sensitive_key(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_sensitive_key(child) for child in value)
    return False


__all__ = ["ApprovedRealRunJob", "RealClientConfig", "RealRunClient", "RealRunDispatchUnavailable", "RealRunProtocolError", "canonical_json", "agent_card_digest"]
