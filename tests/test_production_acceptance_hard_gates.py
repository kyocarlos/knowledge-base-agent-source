from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from production_acceptance_hard_gates import (
    capture_before_rollback,
    evaluate_cleanup_probe,
    validate_failure_bundle,
    validate_production_evidence_root,
)


class ProductionAcceptanceHardGateTests(unittest.TestCase):
    def test_evidence_root_requires_json(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "attempt.json").write_text("{}", encoding="utf-8")
            self.assertTrue(validate_production_evidence_root(root)["validated"])

    def test_missing_evidence_root_fails_closed(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                validate_production_evidence_root(Path(directory) / "missing")

    def test_cleanup_backend_probe_is_fail_closed(self):
        self.assertEqual(evaluate_cleanup_probe(503, {}), {"status": 503, "available": False, "fail_closed": True})
        self.assertEqual(evaluate_cleanup_probe(200, {"backend": "available"})["available"], True)

    def test_capture_failure_does_not_block_rollback(self):
        events: list[str] = []

        def capture():
            events.append("capture")
            raise RuntimeError("diagnostic unavailable")

        def rollback():
            events.append("rollback")
            return "PASS"

        result = capture_before_rollback(capture, rollback)
        self.assertEqual(events, ["capture", "rollback"])
        self.assertEqual(result["capture_status"], "PARTIAL_FAIL")
        self.assertEqual(result["rollback_result"], "PASS")

    def test_failure_bundle_requires_failure_window(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps({"failure_window": {"captured": True}}), encoding="utf-8")
            self.assertTrue(validate_failure_bundle(path)["persisted"])

    def test_failure_bundle_without_window_fails_closed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bundle.json"
            path.write_text(json.dumps({}), encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_failure_bundle(path)


if __name__ == "__main__":
    unittest.main()
