"""HTTP client for the controlled Excel report upload workflow."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

import requests


TERMINAL_STATUSES = {"completed", "ingest_failed", "rejected", "validation_failed"}


class UploadWorkflowError(RuntimeError):
    """A sanitized, actionable workflow failure."""


def request_verify(environ: dict[str, str]) -> str | bool:
    """Resolve TLS verification from the controlled client environment."""
    ca_cert = environ.get("KB_CA_CERT", "").strip()
    if ca_cert:
        return ca_cert
    if environ.get("KB_INGEST_ALLOW_INSECURE_TLS", "false").lower() in {"1", "true", "yes"}:
        return False
    return True


def _redact(value: str) -> str:
    text = str(value or "")
    for marker in ("Authorization", "Bearer", "password", "token", "api_key", "secret"):
        if marker.lower() in text.lower():
            return "[REDACTED]"
    return text[:1000]


@dataclass(frozen=True)
class KMAuth:
    agent_id: str
    agent_token: str
    reviewer_id: str | None = None
    reviewer_token: str | None = None
    e2e_test_mode: bool = False
    test_run_prefix: str | None = None

    def agent_headers(self, run_id: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.agent_token}",
            "X-Agent-ID": self.agent_id,
            "Idempotency-Key": run_id,
        }
        if self.e2e_test_mode:
            headers.update({"X-E2E-Test-Mode": "true", "X-E2E-Agent-ID": self.agent_id, "X-E2E-Test-Run-ID": run_id})
        return headers

    def reviewer_headers(self) -> dict[str, str]:
        if not self.reviewer_id or not self.reviewer_token:
            raise UploadWorkflowError("reviewer credential is required for approval")
        headers = {"Authorization": f"Bearer {self.reviewer_token}"}
        if self.e2e_test_mode:
            headers.update({"X-E2E-Test-Mode": "true", "X-E2E-Reviewer-ID": self.reviewer_id})
        return headers


class KMReportClient:
    def __init__(self, base_url: str, auth: KMAuth, *, verify: str | bool = True, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.verify = verify
        self.session = session or requests.Session()

    @staticmethod
    def _json(response: requests.Response, operation: str) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise UploadWorkflowError(f"{operation} returned non-JSON HTTP {response.status_code}") from exc
        if not isinstance(body, dict):
            raise UploadWorkflowError(f"{operation} returned invalid JSON HTTP {response.status_code}")
        return body

    def upload(self, report_path: str, attachments: list[str], run_id: str) -> dict[str, Any]:
        handles = []
        try:
            report = open(report_path, "rb")
            handles.append(report)
            files = [("file", (report_path.split("/")[-1].split("\\")[-1], report, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))]
            for path in attachments:
                handle = open(path, "rb")
                handles.append(handle)
                name = path.split("/")[-1].split("\\")[-1]
                files.append(("attachments", (name, handle, "application/octet-stream")))
            response = self.session.post(
                f"{self.base_url}/api/agent/v1/reports",
                headers=self.auth.agent_headers(run_id), files=files,
                verify=self.verify, timeout=(15, 120),
            )
        except (OSError, requests.RequestException) as exc:
            raise UploadWorkflowError(f"upload transport failure: {_redact(exc)}") from exc
        finally:
            for handle in handles:
                handle.close()
        body = self._json(response, "upload")
        if response.status_code != 202:
            raise UploadWorkflowError(f"upload rejected HTTP {response.status_code}: {_redact(body.get('detail', body))}")
        return body

    def status(self, submission_id: str, run_id: str) -> dict[str, Any]:
        try:
            response = self.session.get(
                f"{self.base_url}/api/agent/v1/reports/{submission_id}",
                headers=self.auth.agent_headers(run_id), verify=self.verify, timeout=(15, 30),
            )
        except requests.RequestException as exc:
            raise UploadWorkflowError(f"status transport failure: {_redact(exc)}") from exc
        body = self._json(response, "status")
        if response.status_code != 200:
            raise UploadWorkflowError(f"status rejected HTTP {response.status_code}: {_redact(body.get('detail', body))}")
        return body

    def approve_test_only(self, submission_id: str, run_id: str) -> dict[str, Any]:
        if not self.auth.e2e_test_mode or not self.auth.test_run_prefix or not run_id.startswith(self.auth.test_run_prefix):
            raise UploadWorkflowError("automatic approval is restricted to configured disposable test runs")
        try:
            response = self.session.post(
                f"{self.base_url}/api/admin/v1/report-submissions/{submission_id}/approve",
                headers=self.auth.reviewer_headers(), json={"comment": "controlled disposable outbox validation"},
                verify=self.verify, timeout=(15, 30),
            )
        except requests.RequestException as exc:
            raise UploadWorkflowError(f"approval transport failure: {_redact(exc)}") from exc
        body = self._json(response, "approval")
        if response.status_code != 200:
            raise UploadWorkflowError(f"approval rejected HTTP {response.status_code}: {_redact(body.get('detail', body))}")
        return body

    def wait_for_completion(self, submission_id: str, run_id: str, *, attempts: int = 90, interval: float = 2.0, sleeper: Callable[[float], None] = time.sleep) -> dict[str, Any]:
        last: dict[str, Any] = {}
        for attempt in range(max(1, attempts)):
            last = self.status(submission_id, run_id)
            if last.get("status") in TERMINAL_STATUSES:
                return last
            if attempt + 1 < attempts:
                sleeper(max(0.0, interval))
        raise UploadWorkflowError(f"ingest polling timeout after {attempts} attempts; last_status={last.get('status')}")


def load_client_from_env(environ: dict[str, str] | None = None) -> KMReportClient:
    import os

    env = environ or os.environ
    required = ("KB_BASE_URL", "KB_AGENT_ID", "KB_INGEST_TOKEN")
    missing = [name for name in required if not env.get(name, "").strip()]
    if missing:
        raise UploadWorkflowError(f"missing configuration: {', '.join(missing)}")
    e2e = env.get("KB_E2E_TEST_MODE", "false").lower() in {"1", "true", "yes"}
    auth = KMAuth(
        agent_id=env["KB_AGENT_ID"], agent_token=env["KB_INGEST_TOKEN"],
        reviewer_id=env.get("KB_REVIEWER_ID") or None, reviewer_token=env.get("KB_REVIEWER_TOKEN") or None,
        e2e_test_mode=e2e, test_run_prefix=env.get("KB_E2E_TEST_RUN_PREFIX") or None,
    )
    return KMReportClient(env["KB_BASE_URL"], auth, verify=request_verify(env))
