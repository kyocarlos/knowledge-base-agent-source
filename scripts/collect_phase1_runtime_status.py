#!/usr/bin/env python3
"""Collect a sanitized, read-only Phase 1 runtime reconciliation snapshot."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SERVICES = ("kb-web", "kb-celery-search", "kb-celery-ingest", "kb-celery-beat")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def command(args: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(args, capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def probe(url: str, *, insecure_tls: bool, timeout: float) -> dict[str, object]:
    context = ssl._create_unverified_context() if insecure_tls and url.startswith("https://") else None
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return {"http_status": response.status, "data": payload.get("data", payload)}
    except urllib.error.HTTPError as exc:
        return {"http_status": exc.code, "error": "http_error"}
    except (OSError, ValueError) as exc:
        return {"http_status": 0, "error": type(exc).__name__}


def inspect_container(container: str) -> dict[str, object]:
    rc, out, _ = command(["docker", "inspect", container, "--format", "{{.Image}}|{{.State.Status}}"])
    if rc != 0 or "|" not in out:
        return {"container": container, "status": "UNAVAILABLE"}
    image, status = out.split("|", 1)
    return {"container": container, "image_id": image, "status": status}


def broker_status(path: Path, *, timeout: float) -> dict[str, object]:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(path))
        client.sendall(b"GET /v1/status HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        chunks: list[bytes] = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        client.close()
    raw = b"".join(chunks)
    header, separator, body = raw.partition(b"\r\n\r\n")
    if not separator or not header.startswith(b"HTTP/1.1 200"):
        raise RuntimeError("status broker request failed")
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != "km.status-broker.v1":
        raise RuntimeError("status broker schema mismatch")
    return payload


def compare(manifest: dict[str, object], snapshot: dict[str, object]) -> str:
    release = manifest["deployed_release"]
    version = snapshot["version"]
    services = snapshot["services"]
    if version.get("health_status") != 200 or version.get("version_status") != 200:
        return "STALE"
    if any(services.get(name, {}).get("status") != "running" for name in SERVICES):
        return "STALE"
    expected_images = release["service_images"]
    if any(services.get(name, {}).get("image_id") != expected_images.get(name) for name in SERVICES):
        return "MISMATCH"
    if release.get("deployment_state") == "RELEASE":
        git = snapshot["git"]
        if not git.get("clean") or git.get("head") != release.get("operational_runner_commit"):
            return "MISMATCH"
        data = version.get("data", {})
        if any(data.get(key) != release.get(expected_key) for key, expected_key in {
            "commit": "application_commit",
            "release_id": "release_id",
            "image_digest": "image_digest",
            "build_timestamp": "build_timestamp",
        }.items()):
            return "MISMATCH"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--broker-socket", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--insecure-tls", action="store_true")
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.broker_socket and (args.source_root or args.base_url):
        raise SystemExit("FAIL_CLOSED: broker mode cannot be combined with direct host probes")
    if args.broker_socket:
        broker = broker_status(args.broker_socket, timeout=args.timeout)
        git = broker["git"]
        version_result = broker["version"]
        containers = broker["services"]
        source_root = "broker-managed"
    else:
        if not args.source_root or not args.base_url:
            raise SystemExit("FAIL_CLOSED: source-root and base-url are required without broker")
        if shutil.which("git") is None or shutil.which("docker") is None:
            raise SystemExit("FAIL_CLOSED: git and docker are required")
        head_rc, head, _ = command(["git", "-C", str(args.source_root), "rev-parse", "HEAD"])
        status_rc, status, _ = command(["git", "-C", str(args.source_root), "status", "--porcelain"])
        version = probe(args.base_url.rstrip("/") + "/api/v1/version", insecure_tls=args.insecure_tls, timeout=args.timeout)
        health = probe(args.base_url.rstrip("/") + "/health", insecure_tls=args.insecure_tls, timeout=args.timeout)
        version_data = version.get("data") if isinstance(version.get("data"), dict) else {}
        git = {"head": head if head_rc == 0 else None, "clean": status_rc == 0 and not status}
        version_result = {
            "health_status": health.get("http_status"),
            "version_status": version.get("http_status"),
            "data": {key: version_data.get(key) for key in ("commit", "release_id", "image_digest", "build_timestamp")},
        }
        containers = {name: inspect_container(name) for name in ("kb-web", "kb-celery-search", "kb-celery-ingest", "kb-celery-beat")}
        source_root = str(args.source_root)
    snapshot = {
        "schema": "km.phase1-runtime-status.v1",
        "collected_at": utc_now(),
        "manifest": str(args.manifest),
        "collector_mode": "broker" if args.broker_socket else "direct",
        "source_root": source_root,
        "git": git,
        "version": version_result,
        "services": containers,
        "status": compare(manifest, {"git": git, "version": version_result, "services": containers}),
        "production_touched": False,
        "secrets_included": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": snapshot["status"], "output": str(args.output)}))
    return 0 if snapshot["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
