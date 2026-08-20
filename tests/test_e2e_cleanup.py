from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.test_reports.e2e_cleanup import _qdrant_client, build_cleanup_plan
from src.test_reports.registry import SubmissionRegistry
from src.web_api.e2e_cleanup_routes import router


class CleanupPlanTests(unittest.TestCase):
    def test_qdrant_cleanup_uses_configured_kb_endpoint(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "src.main.load_config", return_value={"qdrant": {"url": "http://kb-qdrant:6333"}}
        ), patch("src.runtime_config.resolve_qdrant_url", side_effect=lambda value: value), patch(
            "qdrant_client.QdrantClient"
        ) as client:
            _qdrant_client()
        client.assert_called_once_with(url="http://kb-qdrant:6333", timeout=30)

    def test_namespace_is_fail_closed(self):
        with patch.dict(os.environ, {"KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX": "TR-E2E-WP0-"}):
            with self.assertRaises(ValueError):
                build_cleanup_plan("production-report-001")

    def test_registry_can_find_and_delete_exact_run(self):
        with tempfile.TemporaryDirectory() as directory:
            db = f"sqlite:///{Path(directory) / 'registry.sqlite3'}"
            registry = SubmissionRegistry(db)
            item = {
                "submission_id": "e2e-submission",
                "environment": "anritsu",
                "run_id": "TR-E2E-WP0-20260819-registry",
                "agent_id": "e2e-agent",
                "report_name": "synthetic.xlsx",
                "report_hash": hashlib.sha256(b"fixture").hexdigest(),
                "original_path": str(Path(directory) / "synthetic.xlsx"),
                "attachments": [],
                "manifest": {"run_id": "TR-E2E-WP0-20260819-registry"},
                "validation": {"valid": True},
            }
            registry.create(item)
            self.assertEqual(len(registry.find_by_run_any_environment(item["run_id"])), 1)
            self.assertTrue(registry.delete_by_submission_id(item["submission_id"], item["run_id"]))
            self.assertEqual(registry.find_by_run_any_environment(item["run_id"]), [])


class CleanupRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(router)
        self.token = "e2e-cleanup-test-token"
        self.env = patch.dict(os.environ, {
            "KB_E2E_CLEANUP_ENABLED": "true",
            "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX": "TR-E2E-WP0-",
            "KB_E2E_CLEANUP_TOKEN_HASHES_JSON": json.dumps({
                "test-cleaner": hashlib.sha256(self.token.encode()).hexdigest()
            }),
        })
        self.env.start()
        self.client = TestClient(self.app)

    def tearDown(self):
        self.env.stop()

    def headers(self):
        return {"Authorization": f"Bearer {self.token}", "X-E2E-Cleanup-ID": "test-cleaner"}

    def test_disabled_is_not_discoverable(self):
        with patch.dict(os.environ, {"KB_E2E_CLEANUP_ENABLED": "false"}):
            response = self.client.post("/api/internal/e2e/v1/runs/TR-E2E-WP0-001/cleanup")
        self.assertEqual(response.status_code, 404)

    def test_dry_run_requires_scoped_credential(self):
        response = self.client.post("/api/internal/e2e/v1/runs/TR-E2E-WP0-001/cleanup")
        self.assertEqual(response.status_code, 401)

    def test_dry_run_and_apply_are_separate(self):
        with patch("src.web_api.e2e_cleanup_routes.build_cleanup_plan", return_value={"test_run_id": "TR-E2E-WP0-001", "active_task_count": 0}), patch("src.web_api.e2e_cleanup_routes.apply_cleanup", return_value={"test_run_id": "TR-E2E-WP0-001", "deleted": {"files": 1}}) as apply:
            dry_run = self.client.post("/api/internal/e2e/v1/runs/TR-E2E-WP0-001/cleanup", headers=self.headers(), json={"apply": False})
            applied = self.client.post("/api/internal/e2e/v1/runs/TR-E2E-WP0-001/cleanup", headers=self.headers(), json={"apply": True})
        self.assertEqual(dry_run.status_code, 200)
        self.assertEqual(dry_run.json()["mode"], "dry-run")
        self.assertEqual(applied.status_code, 200)
        self.assertEqual(applied.json()["mode"], "apply")
        apply.assert_called_once_with("TR-E2E-WP0-001", None)


if __name__ == "__main__":
    unittest.main()
