from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openpyxl import Workbook

from scripts import run_wp1_production_acceptance as runner
from scripts.websocket_crypto_preflight import implementation_sha256


class ProductionAcceptanceRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.run_id = "TR-E2E-WP1-PROD-RUNNER-UNIT-20260828-abcdef12"
        self.fixture = self.root / f"{self.run_id}.xlsx"
        self.attachment = self.root / "synthetic-e2e-log.txt"
        self.attachment.write_text("synthetic only\n", encoding="utf-8")
        book = Workbook()
        manifest = book.active
        manifest.title = "Manifest"
        manifest.append(["key", "value"])
        manifest.append(["run_id", self.run_id])
        manifest.append(["test_run_id", self.run_id])
        artifacts = book.create_sheet("RawArtifacts")
        artifacts.append(["artifact_path", "sha256"])
        artifacts.append([self.attachment.name, hashlib.sha256(self.attachment.read_bytes()).hexdigest()])
        book.save(self.fixture)
        self.credentials = self.root / "credentials.env"
        self.credentials.write_text("\n".join(f"{key}=test-{key.lower()}" for key in runner.EXPECTED_SECRET_KEYS) + "\n", encoding="utf-8")
        self.evidence_root = self.root / "evidence"
        self.evidence_root.mkdir()
        (self.evidence_root / "prior-production-acceptance.json").write_text(json.dumps({"production_touched": True, "run_id": "TR-E2E-WP1-PROD-OLD-20260828-12345678"}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def args(self) -> object:
        return type("Args", (), {
            "source_root": self.root,
            "expected_git_head": "approved-head",
            "expected_runner_sha256": hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
            "expected_crypto_sha256": implementation_sha256(),
            "expected_commit": "a" * 40,
            "expected_release_id": "test-release",
            "expected_image_id": "sha256:" + "b" * 64,
            "expected_build_timestamp": "2026-08-28T00:00:00+00:00",
            "fixture": self.fixture,
            "attachment": self.attachment,
            "run_id": self.run_id,
            "production_evidence_root": self.evidence_root,
        })()

    def test_pre_network_identity_gate_passes_without_network(self) -> None:
        with mock.patch.object(runner, "git_head", return_value="approved-head"):
            result = runner.pre_network_identity_gate(self.args(), runner.read_env(self.credentials))
        self.assertEqual(result["run_id_uniqueness_gate"], "PASS")
        self.assertFalse(result["network_or_write_started"])
        self.assertEqual(result["request_contract"]["X-E2E-Test-Run-ID"], self.run_id)

    def test_git_or_runner_mismatch_fails_before_run_id_scan(self) -> None:
        calls: list[str] = []
        with mock.patch.object(runner, "check_unique_production_run_id", side_effect=lambda *_: calls.append("scan")):
            with mock.patch.object(runner, "git_head", return_value="wrong-head"):
                with self.assertRaises(runner.AcceptanceGateError):
                    runner.pre_network_identity_gate(self.args(), runner.read_env(self.credentials))
        self.assertEqual(calls, [])

    def test_runner_uses_shared_crypto_helper(self) -> None:
        source = Path(runner.__file__).read_text(encoding="utf-8")
        self.assertIn("crypto_preflight(", source)
        self.assertIn("serialize_connect_payload(", source)
        self.assertNotIn("private_key.sign(", source)

    def test_non_local_isolated_target_is_rejected(self) -> None:
        args = self.args()
        args.base_url = "http://192.0.2.10:8000"
        args.production = False
        self.assertFalse(args.base_url.startswith(("http://127.0.0.1:", "http://localhost:")))

    def test_full_isolated_runner_sequence_uses_gates_before_writes(self) -> None:
        args = self.args()
        args.base_url = "http://127.0.0.1:18888"
        args.credentials_env = self.credentials
        args.evidence_out = self.root / "runner-evidence.json"
        args.production = False
        args.ingest_poll_attempts = 1
        args.ingest_poll_interval = 0
        sequence: list[str] = []

        def fake_request(url, *_args, **_kwargs):
            if url.endswith("/health"):
                return 200, '{"status":"healthy"}'
            if url.endswith("/api/v1/version"):
                return 200, json.dumps({"data": {"commit": args.expected_commit, "release_id": args.expected_release_id, "image_digest": args.expected_image_id, "build_timestamp": args.expected_build_timestamp}})
            if "/report-submissions/submission-1" in url and "/api/admin/" in url:
                if sequence and sequence[-1] == "cleanup":
                    return 404, "{}"
                return 200, '{"status":"completed"}'
            if "/api/agent/" in url:
                return 200, "{}"
            raise AssertionError(url)

        def fake_post_json(url, payload, *_args, **_kwargs):
            if url.endswith("/search"):
                sequence.append("search")
                return 200, '{"task_id":"search-1"}'
            if url.endswith("/approve"):
                sequence.append("approve")
                return 200, "{}"
            if url.endswith("/cleanup"):
                if payload["apply"]:
                    sequence.append("cleanup")
                    return 200, '{"mode":"apply"}'
                return 200, '{"mode":"dry-run"}'
            raise AssertionError(url)

        def fake_multipart(*_args, **_kwargs):
            sequence.append("upload")
            if sequence.count("upload") == 1:
                return 202, '{"submission_id":"submission-1"}'
            return 202, '{"duplicate":true}'

        with mock.patch.object(runner, "git_head", return_value="approved-head"), \
             mock.patch.object(runner, "request", side_effect=fake_request), \
             mock.patch.object(runner, "post_json", side_effect=fake_post_json), \
             mock.patch.object(runner, "post_multipart", side_effect=fake_multipart), \
             mock.patch.object(runner, "websocket_exchange", return_value={"handshake": True, "ready": True, "chat_sent": True, "final": True, "close_code": 1000, "frames": []}) as websocket:
            result = runner.run_acceptance(args)
        self.assertEqual(result["result"], "PASS")
        self.assertEqual(sequence, ["search", "upload", "upload", "approve", "cleanup"])
        websocket.assert_called_once_with(args.base_url, args.run_id)
        self.assertEqual(json.loads(args.evidence_out.read_text(encoding="utf-8"))["residual_count"], 0)
