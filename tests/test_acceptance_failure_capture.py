import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.run_wp1_production_acceptance import (
    _capture_failure_window,
    _failure_stage_summary,
)


class AcceptanceFailureCaptureTests(unittest.TestCase):
    def test_stage_summary_redacts_and_classifies_missing_credential(self):
        summary = _failure_stage_summary(
            {"status": "ingest_failed", "embedding_status": "failed"},
            "Missing OpenAI-compatible API credential: SUB2API_API_KEY",
        )
        self.assertTrue(summary["credential_missing_message"])
        self.assertEqual(summary["embedding"], "FAIL")
        self.assertFalse(summary["embedding_request_attempted"])

    def test_failure_window_persists_diagnostic_without_secret_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = SimpleNamespace(
                evidence_out=Path(tmp) / "acceptance.json",
                run_id="TR-E2E-TEST-001",
                web_container="kb-web",
                nginx_container="kb-nginx",
                ingest_worker_container="kb-celery-ingest",
            )
            evidence = {"runtime_identity": {"metadata": {"image_digest": "sha256:test"}}, "request_observations": []}
            report = {
                "status": "ingest_failed",
                "ingest_task_id": "task-001",
                "error": {"message": "password=do-not-persist"},
                "updated_at": "2026-09-04T00:00:00Z",
            }

            def fake_run(command, **kwargs):
                output = "" if "logs" not in command else "worker ingest failed\n"
                return SimpleNamespace(returncode=0, stdout=output, stderr="")

            with patch("scripts.run_wp1_production_acceptance.subprocess.run", side_effect=fake_run), patch(
                "scripts.run_wp1_production_acceptance._container_env_presence", return_value=True
            ):
                result = _capture_failure_window(
                    args, evidence, submission_id="report-001", last_report=report
                )

            self.assertEqual(result["status"], "PASS")
            diagnostic = json.loads((Path(tmp) / "failure-window-TR-E2E-TEST-001" / "diagnostic.json").read_text())
            self.assertEqual(diagnostic["ingest_job_id"], "task-001")
            self.assertTrue(diagnostic["SUB2API_API_KEY_PRESENT"])
            self.assertNotIn("do-not-persist", json.dumps(diagnostic))
            self.assertIn("[REDACTED]", json.dumps(diagnostic))


if __name__ == "__main__":
    unittest.main()
