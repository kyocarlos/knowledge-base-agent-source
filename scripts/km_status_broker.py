#!/usr/bin/env python3
"""Expose a fixed, sanitized read-only runtime status endpoint over Unix socket."""

from __future__ import annotations

import argparse
import json
import socket
import socketserver
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SERVICES = ("kb-web", "kb-celery-search", "kb-celery-ingest", "kb-celery-beat")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_fixed(args: list[str]) -> tuple[int, str]:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip()


def probe(url: str, *, insecure_tls: bool, timeout: float) -> dict[str, object]:
    context = ssl._create_unverified_context() if insecure_tls and url.startswith("https://") else None
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            payload = json.loads(response.read().decode("utf-8"))
            data = payload.get("data", payload)
            return {"http_status": response.status, "data": data if isinstance(data, dict) else {}}
    except urllib.error.HTTPError as exc:
        return {"http_status": exc.code, "error": "http_error"}
    except (OSError, ValueError) as exc:
        return {"http_status": 0, "error": type(exc).__name__}


def collect(config: argparse.Namespace) -> dict[str, object]:
    head_rc, head = run_fixed(["git", "-C", str(config.source_root), "rev-parse", "HEAD"])
    status_rc, status = run_fixed(["git", "-C", str(config.source_root), "status", "--porcelain"])
    health = probe(config.base_url.rstrip("/") + "/health", insecure_tls=config.insecure_tls, timeout=config.timeout)
    version = probe(config.base_url.rstrip("/") + "/api/v1/version", insecure_tls=config.insecure_tls, timeout=config.timeout)
    services: dict[str, dict[str, object]] = {}
    for service in SERVICES:
        rc, output = run_fixed([
            config.docker_bin,
            "inspect",
            service,
            "--format",
            "{{.Image}}|{{.State.Status}}",
        ])
        if rc != 0 or "|" not in output:
            services[service] = {"status": "UNAVAILABLE"}
        else:
            image_id, service_status = output.split("|", 1)
            services[service] = {"image_id": image_id, "status": service_status}
    version_data = version.get("data") if isinstance(version.get("data"), dict) else {}
    return {
        "schema": "km.status-broker.v1",
        "collected_at": now(),
        "git": {"head": head if head_rc == 0 else None, "clean": status_rc == 0 and not status},
        "version": {
            "health_status": health.get("http_status"),
            "version_status": version.get("http_status"),
            "data": {key: version_data.get(key) for key in ("commit", "release_id", "image_digest", "build_timestamp")},
        },
        "services": services,
        "secrets_included": False,
    }


class BrokerServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        request = self.rfile.readline(4096).decode("ascii", "replace").strip()
        if request != "GET /v1/status HTTP/1.1":
            self._reply(404, {"error": "not_found"})
            return
        while True:
            line = self.rfile.readline(4096)
            if not line or line in (b"\r\n", b"\n"):
                break
        payload = collect(self.server.config)  # type: ignore[attr-defined]
        self._reply(200, payload)

    def _reply(self, status: int, payload: dict[str, object]) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.wfile.write(
            f"HTTP/1.1 {status} {'OK' if status == 200 else 'Not Found'}\r\n"
            "Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Connection: close\r\n\r\n".encode("ascii")
            + body
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--docker-bin", default="docker")
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--insecure-tls", action="store_true")
    config = parser.parse_args()
    if config.socket.exists():
        config.socket.unlink()
    config.socket.parent.mkdir(parents=True, exist_ok=True)
    server = BrokerServer(str(config.socket), Handler)
    server.config = config
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
