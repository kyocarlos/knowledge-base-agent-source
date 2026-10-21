from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.verify_write_e2e_gate import verify


class WriteE2EGateTests(unittest.TestCase):
    def evidence(self) -> dict:
        return {
            "test_run_id": "TR-E2E-WP0-20260819-072514",
            "production_services_touched": False,
            "result": "passed",
            "checks": {
                "report_upload": "HTTP 202",
                "review_approve_and_queue": "HTTP 200",
                "worker_terminal_state": "completed",
                "cleanup_dry_run": "HTTP 200",
                "cleanup_apply": "HTTP 200",
                "submission_after_cleanup": "HTTP 404",
                "neo4j_scoped_counts_before_cleanup": {"TestRun": 1, "TestCase": 1, "Measurement": 1},
                "neo4j_deleted_counts": {"TestRun": 1, "TestCase": 1, "Measurement": 1},
                "qdrant_scoped_points_before_cleanup": 4,
                "qdrant_deleted_points": 4,
            },
        }

    def test_shadow_evidence_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(self.evidence()), encoding="utf-8")
            result = verify(path)
        self.assertEqual(result["decision"], "SHADOW_WRITE_E2E_PASS")
        self.assertFalse(result["production_ready"])

    def test_production_touched_is_rejected(self):
        evidence = self.evidence()
        evidence["production_services_touched"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(evidence), encoding="utf-8")
            with self.assertRaises(ValueError):
                verify(path)


if __name__ == "__main__":
    unittest.main()
