#!/usr/bin/env python3
"""Collect a sanitized, read-only Phase 1 runtime reconciliation snapshot."""

from __future__ import annotations

import argparse
import json
import shutil
import ssl
import subprocess
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


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


def compare(manifest: dict[str, object], snapshot: dict[str, object]) -> str:
    release = manifest["approved_release"]
    git = snapshot["git"]
    version = snapshot["version"]
    services = snapshot["services"]
    if not git.get("clean") or git.get("head") != release["operational_runner_commit"]:
        return "MISMATCH"
    if version.get("health_status") != 200 or version.get("version_status") != 200:
        return "STALE"
    data = version.get("data", {})
    if any(data.get(key) != value for key, value in {
        "commit": release["application_commit"],
        "release_id": release["release_id"],
        "image_digest": release["image_digest"],
        "build_timestamp": release["build_timestamp"],
    }.items()):
        return "MISMATCH"
    expected_containers = ("kb-web", "kb-celery-search", "kb-celery-ingest", "kb-celery-beat")
    if any(services.get(name, {}).get("status") != "running" for name in expected_containers):
        return "STALE"
    if any(services.get(name, {}).get("image_id") != release["image_digest"] for name in expected_containers):
        return "MISMATCH"
    return "PASS"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--insecure-tls", action="store_true")
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if shutil.which("git") is None or shutil.which("docker") is None:
        raise SystemExit("FAIL_CLOSED: git and docker are required")
    head_rc, head, _ = command(["git", "-C", str(args.source_root), "rev-parse", "HEAD"])
    status_rc, status, _ = command(["git", "-C", str(args.source_root), "status", "--porcelain"])
    version = probe(args.base_url.rstrip("/") + "/api/v1/version", insecure_tls=args.insecure_tls, timeout=args.timeout)
    health = probe(args.base_url.rstrip("/") + "/health", insecure_tls=args.insecure_tls, timeout=args.timeout)
    version_data = version.get("data") if isinstance(version.get("data"), dict) else {}
    version_result = {
        "health_status": health.get("http_status"),
        "version_status": version.get("http_status"),
        "data": {key: version_data.get(key) for key in ("commit", "release_id", "image_digest", "build_timestamp")},
    }
    containers = {
        name: inspect_container(name)
        for name in ("kb-web", "kb-celery-search", "kb-celery-ingest", "kb-celery-beat")
    }
    snapshot = {
        "schema": "km.phase1-runtime-status.v1",
        "collected_at": utc_now(),
        "manifest": str(args.manifest),
        "source_root": str(args.source_root),
        "git": {"head": head if head_rc == 0 else None, "clean": status_rc == 0 and not status},
        "version": version_result,
        "services": containers,
        "status": compare(manifest, {"git": {"head": head if head_rc == 0 else None, "clean": status_rc == 0 and not status}, "version": version_result, "services": containers}),
        "production_touched": False,
        "secrets_included": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": snapshot["status"], "output": str(args.output)}))
    return 0 if snapshot["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
