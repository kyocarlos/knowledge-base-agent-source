from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from src.test_reports.auth import authenticate_e2e_agent, authenticate_e2e_cleanup, authenticate_e2e_reviewer
from src.web_api.e2e_cleanup_routes import router as cleanup_router
from src.web_api.report_routes import router as report_router
from src.web_api.tasks import _attachment_hashes_from_state


class E2ECredentialTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(cleanup_router)
        self.app.include_router(report_router)
        self.agent_token = "synthetic-agent-token"
        self.reviewer_token = "synthetic-reviewer-token"
        self.cleanup_token = "synthetic-cleanup-token"
        self.env = patch.dict(os.environ, {
            "KB_E2E_WRITE_MODE_ENABLED": "true",
            "KB_E2E_AGENT_TOKEN_HASHES_JSON": json.dumps({"e2e-agent-01": {"environment": "anritsu", "token_sha256": hashlib.sha256(self.agent_token.encode()).hexdigest()}}),
            "KB_E2E_REVIEWER_TOKEN_HASHES_JSON": json.dumps({"e2e-reviewer-01": hashlib.sha256(self.reviewer_token.encode()).hexdigest()}),
            "KB_E2E_CLEANUP_ENABLED": "true",
            "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX": "TR-E2E-WP0-",
            "KB_E2E_CLEANUP_TOKEN_HASHES_JSON": json.dumps({"e2e-cleanup-01": hashlib.sha256(self.cleanup_token.encode()).hexdigest()}),
        })
        self.env.start()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.env.stop()

    def test_each_role_is_separate(self):
        agent_request = type("Request", (), {"headers": {"X-E2E-Agent-ID": "e2e-agent-01", "Authorization": f"Bearer {self.agent_token}"}})()
        reviewer_request = type("Request", (), {"headers": {"X-E2E-Reviewer-ID": "e2e-reviewer-01", "Authorization": f"Bearer {self.reviewer_token}"}})()
        cleanup_request = type("Request", (), {"headers": {"X-E2E-Cleanup-ID": "e2e-cleanup-01", "Authorization": f"Bearer {self.cleanup_token}"}})()
        self.assertEqual(authenticate_e2e_agent(agent_request)["scope"], "report:upload")
        self.assertEqual(authenticate_e2e_agent(agent_request)["environment"], "anritsu")
        self.assertEqual(authenticate_e2e_reviewer(reviewer_request)["scope"], "report:review")
        self.assertEqual(authenticate_e2e_cleanup(cleanup_request)["scope"], "e2e:cleanup")

    def test_cleanup_token_cannot_authenticate_agent(self):
        request = type("Request", (), {"headers": {"X-E2E-Agent-ID": "e2e-agent-01", "Authorization": f"Bearer {self.cleanup_token}"}})()
        with self.assertRaises(Exception):
            authenticate_e2e_agent(request)

    def test_cleanup_endpoint_still_requires_cleanup_role(self):
        response = self.client.post(
            "/api/internal/e2e/v1/runs/TR-E2E-WP0-001/cleanup",
            headers={"X-E2E-Cleanup-ID": "e2e-cleanup-01", "Authorization": "Bearer wrong"},
        )
        self.assertEqual(response.status_code, 403)

    def test_e2e_write_mode_is_disabled_without_header(self):
        with patch.dict(os.environ, {"KB_E2E_WRITE_MODE_ENABLED": "false"}):
            request = type("Request", (), {"headers": {"X-E2E-Test-Mode": "true", "X-E2E-Agent-ID": "e2e-agent-01", "Authorization": f"Bearer {self.agent_token}"}})()
            with self.assertRaises(Exception):
                from src.test_reports.auth import authenticate_report_agent
                authenticate_report_agent(request)

    def test_worker_preserves_validated_attachment_hashes(self):
        digest = "a" * 64
        state = {"attachments": [{"name": "nested/synthetic.log", "sha256": digest}]}
        self.assertEqual(_attachment_hashes_from_state(state), {"synthetic.log": digest})
        self.assertEqual(_attachment_hashes_from_state({"attachments": [{"name": "bad", "sha256": "wrong"}]}), {})

    def test_scoped_e2e_report_upload_and_review(self):
        test_run_id = "TR-E2E-WP0-20260819-report"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = root / "synthetic.xlsx"
            workbook = Workbook()
            manifest = workbook.active
            manifest.title = "Manifest"
            manifest.append(["key", "value"])
            for key, value in {
                "schema_version": "1.0", "run_id": test_run_id, "test_run_id": test_run_id,
                "environment": "anritsu", "project_code": "E2E-WP0-SYNTHETIC",
                "dut_model": "E2E-DUT", "started_at": "2026-08-19T15:00:00+08:00",
                "finished_at": "2026-08-19T15:01:00+08:00", "overall_verdict": "Pass",
            }.items():
                manifest.append([key, value])
            for name, headers, rows in [
                ("RadioConfig", ["key", "value", "unit"], [["profile", "synthetic", ""]]),
                ("TestCases", ["case_id", "name", "status"], [["E2E-01", "synthetic", "completed"]]),
                ("Measurements", ["case_id", "metric", "value", "unit"], [["E2E-01", "score", 1, "count"]]),
                ("Verdicts", ["case_id", "verdict", "reason"], [["E2E-01", "Pass", "synthetic"]]),
                ("RawArtifacts", ["artifact_path", "sha256"], []),
            ]:
                sheet = workbook.create_sheet(name)
                sheet.append(headers)
                for row in rows:
                    sheet.append(row)
            workbook.save(report)
            headers = {
                "Authorization": f"Bearer {self.agent_token}", "X-E2E-Agent-ID": "e2e-agent-01",
                "X-E2E-Test-Mode": "true", "X-E2E-Test-Run-ID": test_run_id,
                "Idempotency-Key": test_run_id,
            }
            with patch.dict(os.environ, {
                "KB_REPORT_REGISTRY_URL": f"sqlite:///{root / 'reports.sqlite3'}",
                "KB_REPORT_STAGING_ROOT": str(root / "staging"),
            }), report.open("rb") as handle:
                uploaded = self.client.post("/api/agent/v1/reports", headers=headers, files={"file": ("synthetic.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
            self.assertEqual(uploaded.status_code, 202, uploaded.text)
            submission_id = uploaded.json()["submission_id"]
            reviewer_headers = {
                "Authorization": f"Bearer {self.reviewer_token}", "X-E2E-Reviewer-ID": "e2e-reviewer-01", "X-E2E-Test-Mode": "true"
            }
            with patch.dict(os.environ, {
                "KB_REPORT_REGISTRY_URL": f"sqlite:///{root / 'reports.sqlite3'}",
                "KB_REPORT_STAGING_ROOT": str(root / "staging"),
            }), patch("src.web_api.tasks.INGEST_UPLOAD_ROOT", root / "uploads"), patch("src.web_api.tasks.set_ingest_task_state"), patch("src.web_api.tasks.create_ingest_task_id", return_value="e2e-ingest-1"), patch("src.web_api.tasks.ingest_file_task.apply_async", return_value=Mock(id="celery-e2e-1")):
                approved = self.client.post(f"/api/admin/v1/report-submissions/{submission_id}/approve", headers=reviewer_headers, json={"comment": "synthetic E2E"})
            self.assertEqual(approved.status_code, 200)
            self.assertEqual(approved.json()["status"], "queued")


if __name__ == "__main__":
    unittest.main()
