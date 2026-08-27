from __future__ import annotations

import json
import importlib.util
import subprocess
import sys
import threading
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check_deployment_readiness.py"


class Handler(BaseHTTPRequestHandler):
    ready_after = 2
    calls = 0

    def do_GET(self) -> None:  # noqa: N802
        type(self).calls += 1
        if self.path == "/health":
            status, body = (200, {"status": "healthy"}) if type(self).calls > self.ready_after else (503, {"status": "starting"})
        elif self.path == "/api/v1/version":
            status, body = (200, {"data": {"commit": "a" * 40, "release_id": "release", "image_digest": "sha256:" + "b" * 64, "build_timestamp": "2026-08-26T13:58:10+08:00"}}) if type(self).calls > self.ready_after else (503, {"error": "starting"})
        else:
            status, body = 404, {}
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_: object) -> None:
        pass


def test_readiness_is_bounded_and_records_first_success(tmp_path: Path) -> None:
    Handler.calls = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        output = tmp_path / "readiness.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--direct-base-url", base, "--ingress-base-url", base,
             "--timeout-seconds", "3", "--interval-seconds", "0.01", "--expected-commit", "a" * 40,
             "--expected-release-id", "release", "--expected-image-digest", "sha256:" + "b" * 64,
             "--expected-build-timestamp", "2026-08-26T13:58:10+08:00", "--output", str(output)],
            check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        evidence = json.loads(output.read_text())
        assert evidence["result"] == "PASS"
        assert evidence["attempts"] >= 2
        assert evidence["first_success_at"]["direct"]
        assert evidence["first_success_at"]["ingress"]
        assert evidence["last_result"]["ingress"]["passed"] is True
    finally:
        server.shutdown()


def test_https_probe_uses_unverified_tls_context_for_formal_ingress() -> None:
    class FakeHeaders:
        def get(self, name: str, default: str = "") -> str:
            return "application/json" if name == "Content-Type" else default

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def read(self) -> bytes:
            return b'{"status":"healthy"}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    spec = importlib.util.spec_from_file_location("check_deployment_readiness", SCRIPT)
    assert spec and spec.loader
    readiness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(readiness)

    with patch.object(readiness.urllib.request, "urlopen", return_value=FakeResponse()) as urlopen:
        result = readiness.probe("https://formal-ingress.test/health")

    assert result["status"] == 200
    assert result["json"] == {"status": "healthy"}
    assert urlopen.call_args.kwargs["context"] is not None


def test_readiness_replaces_early_failures_with_later_success(tmp_path: Path) -> None:
    Handler.calls = 0
    Handler.ready_after = 8
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        output = tmp_path / "readiness-late-success.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--direct-base-url", base, "--ingress-base-url", base,
             "--timeout-seconds", "3", "--interval-seconds", "0.01", "--output", str(output)],
            check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        evidence = json.loads(output.read_text())
        assert evidence["result"] == "PASS"
        assert evidence["first_success_at"]["ingress"]
        assert evidence["last_result"]["ingress"]["passed"] is True
    finally:
        server.shutdown()
