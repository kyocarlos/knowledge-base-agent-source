from __future__ import annotations

import tempfile
import unittest
import hashlib
import os
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import Workbook

from src.test_reports.excel_contract import ReportValidationError, parse_and_validate_report, render_report_markdown
from src.test_reports.registry import SubmissionConflict, SubmissionRegistry
from src.web_api.report_routes import router


def build_report(path: Path, environment: str = "anritsu", run_id: str = "RUN-001") -> None:
    workbook = Workbook()
    manifest = workbook.active
    manifest.title = "Manifest"
    manifest.append(["key", "value"])
    for key, value in {
        "schema_version": "1.0", "run_id": run_id, "environment": environment,
        "project_code": "NCQ2200B2V", "dut_model": "DUT-A", "started_at": "2026-07-23T08:00:00+08:00",
        "finished_at": "2026-07-23T08:10:00+08:00", "overall_verdict": "Pass",
    }.items():
        manifest.append([key, value])
    sheets = {
        "RadioConfig": (["key", "value", "unit"], [["band", "n78", ""]]),
        "TestCases": (["case_id", "name", "status"], [["TC-01", "TCP DL Throughput", "completed"]]),
        "Measurements": (["case_id", "metric", "value", "unit", "lower_limit", "upper_limit"], [["TC-01", "throughput", 950.5, "Mbps", 900, None]]),
        "Verdicts": (["case_id", "verdict", "reason"], [["TC-01", "Pass", "meets threshold"]]),
        "RawArtifacts": (["artifact_path", "sha256"], []),
    }
    for name, (headers, rows) in sheets.items():
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    workbook.save(path)


class ExcelContractTests(unittest.TestCase):
    def test_valid_report_is_rendered_with_filterable_context(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            build_report(path)
            parsed = parse_and_validate_report(path)
            markdown = render_report_markdown(parsed)
            self.assertEqual(parsed["manifest"]["environment"], "anritsu")
            self.assertIn("## Test Case 1: TC-01", markdown)
            self.assertIn("950.5", markdown)

    def test_invalid_environment_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            build_report(path, environment="unknown")
            with self.assertRaises(ReportValidationError):
                parse_and_validate_report(path)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.registry = SubmissionRegistry(f"sqlite:///{self.directory.name}/registry.sqlite3")

    def tearDown(self):
        self.directory.cleanup()

    def item(self, digest: str = "abc") -> dict:
        return {
            "submission_id": "submission-1", "environment": "anritsu", "run_id": "RUN-001",
            "agent_id": "agent-1", "report_name": "report.xlsx", "report_hash": digest,
            "original_path": "/tmp/report.xlsx", "attachments": [], "manifest": {"run_id": "RUN-001"},
            "validation": {"valid": True},
        }

    def test_same_run_and_hash_is_idempotent(self):
        created, duplicate = self.registry.create(self.item())
        existing, second_duplicate = self.registry.create(self.item())
        self.assertFalse(duplicate)
        self.assertTrue(second_duplicate)
        self.assertEqual(created["submission_id"], existing["submission_id"])

    def test_same_run_with_new_hash_conflicts(self):
        self.registry.create(self.item())
        with self.assertRaises(SubmissionConflict):
            self.registry.create(self.item("different"))

    def test_review_transition_is_single_use(self):
        self.registry.create(self.item())
        approved = self.registry.transition("submission-1", {"pending_review"}, "approved", reviewer_id="reviewer")
        self.assertEqual(approved["status"], "approved")
        with self.assertRaises(SubmissionConflict):
            self.registry.transition("submission-1", {"pending_review"}, "rejected")


class ReportApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.report_path = Path(self.directory.name) / "report.xlsx"
        build_report(self.report_path)
        self.agent_token = "agent-secret"
        self.reviewer_token = "review-secret"
        self.env = patch.dict(os.environ, {
            "KB_REPORT_REGISTRY_URL": f"sqlite:///{self.directory.name}/api.sqlite3",
            "KB_REPORT_STAGING_ROOT": f"{self.directory.name}/staging",
            "KB_AGENT_TOKEN_HASHES_JSON": '{"anritsu-agent-01":{"environment":"anritsu","token_sha256":"' + hashlib.sha256(self.agent_token.encode()).hexdigest() + '"}}',
            "KB_REVIEWER_TOKEN_HASHES_JSON": '{"reviewer-01":"' + hashlib.sha256(self.reviewer_token.encode()).hexdigest() + '"}',
        })
        self.env.start()
        app = FastAPI()
        app.include_router(router)
        self.client = TestClient(app)

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def agent_headers(self):
        return {"Authorization": f"Bearer {self.agent_token}", "X-Agent-ID": "anritsu-agent-01", "Idempotency-Key": "RUN-001"}

    def reviewer_headers(self):
        return {"Authorization": f"Bearer {self.reviewer_token}"}

    def upload(self):
        with self.report_path.open("rb") as handle:
            return self.client.post("/api/agent/v1/reports", headers=self.agent_headers(), files={"file": ("report.xlsx", handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})

    def test_upload_requires_token_and_is_idempotent(self):
        with self.report_path.open("rb") as handle:
            unauthorized = self.client.post("/api/agent/v1/reports", files={"file": ("report.xlsx", handle)})
        self.assertEqual(unauthorized.status_code, 401)
        first = self.upload()
        second = self.upload()
        self.assertEqual(first.status_code, 202)
        self.assertEqual(first.json()["status"], "pending_review")
        self.assertTrue(second.json()["duplicate"])
        self.assertEqual(first.json()["submission_id"], second.json()["submission_id"])

    def test_reviewer_can_approve_once(self):
        submission_id = self.upload().json()["submission_id"]
        async_result = Mock(id="celery-1")
        with patch("src.web_api.tasks.INGEST_UPLOAD_ROOT", Path(self.directory.name) / "uploads"), patch("src.web_api.tasks.set_ingest_task_state"), patch("src.web_api.tasks.create_ingest_task_id", return_value="ingest-1"), patch("src.web_api.tasks.ingest_file_task.apply_async", return_value=async_result):
            approved = self.client.post(
                f"/api/admin/v1/report-submissions/{submission_id}/approve",
                headers=self.reviewer_headers(), json={"comment": "reviewed"},
            )
            repeated = self.client.post(
                f"/api/admin/v1/report-submissions/{submission_id}/approve",
                headers=self.reviewer_headers(), json={"comment": "again"},
            )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "queued")
        self.assertEqual(repeated.status_code, 409)


if __name__ == "__main__":
    unittest.main()
