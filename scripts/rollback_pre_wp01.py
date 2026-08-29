#!/usr/bin/env python3
"""Restore pre-WP0/WP1 application containers without deleting data volumes."""

from __future__ import annotations

import argparse
import hashlib
import json
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def run(args: list[str]) -> None:
    subprocess.run(args, check=True)


def verify(checkpoint: Path) -> dict:
    sums = checkpoint / "SHA256SUMS"
    if not sums.is_file():
        raise RuntimeError("SHA256SUMS is missing")
    for line in sums.read_text().splitlines():
        expected, relative = line.split("  ", 1)
        path = checkpoint / relative
        if not path.is_file():
            raise RuntimeError(f"checksum mismatch: {relative}")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        if hasher.hexdigest() != expected:
            raise RuntimeError(f"checksum mismatch: {relative}")
    return json.loads((checkpoint / "checkpoint.json").read_text())


def image_exists(tag: str) -> bool:
    return subprocess.run(["docker", "image", "inspect", tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def wait_health(url: str, expected: str, timeout: int) -> None:
    context = ssl._create_unverified_context() if url.startswith("https://") else None
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5, context=context) as response:
                body = response.read().decode(errors="replace")
                if response.status == 200 and expected in body:
                    return
                last = f"HTTP {response.status}: {body[:200]}"
        except Exception as exc:  # health retry deliberately records the final transport error
            last = str(exc)
        time.sleep(2)
    raise RuntimeError(f"rollback health check failed: {last}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--project-name", default="knowledge-base")
    parser.add_argument("--project-directory", type=Path)
    parser.add_argument("--compose-file", type=Path)
    parser.add_argument("--override-file", type=Path)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--services", default="web,celery_search_worker,celery_ingest_worker,celery_beat,nginx")
    parser.add_argument("--health-url", default="https://127.0.0.1:3030/health")
    parser.add_argument("--health-contains", default='"healthy"')
    parser.add_argument("--health-timeout", type=int, default=120)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-production", default="")
    args = parser.parse_args()

    checkpoint = args.checkpoint.resolve()
    manifest = verify(checkpoint)
    runtime = checkpoint / "runtime"
    compose_file = (args.compose_file or runtime / "docker-compose.yml").resolve()
    override_file = (args.override_file or runtime / "rollback-images.yml").resolve()
    env_file = (args.env_file or runtime / "rollback.env").resolve()
    project_directory = (args.project_directory or Path(manifest["source_root"])).resolve()
    services = [item.strip() for item in args.services.split(",") if item.strip()]

    if not args.execute:
        print("DRY RUN: checkpoint verified; add --execute to recreate application containers")
        print("services:", ", ".join(services))
        return 0
    if args.project_name == "knowledge-base" and args.confirm_production != "PRE_WP01_ROLLBACK":
        raise RuntimeError("production rollback requires --confirm-production PRE_WP01_ROLLBACK")

    tags = json.loads((checkpoint / "images/image-tags.json").read_text())
    missing = [tags[name] for name in services if name in tags and not image_exists(tags[name])]
    archive = checkpoint / "images/application-images.tar"
    if missing:
        if not archive.is_file():
            raise RuntimeError(f"rollback images are missing and no archive is available: {missing}")
        run(["docker", "image", "load", "-i", str(archive)])
    still_missing = [tag for tag in missing if not image_exists(tag)]
    if still_missing:
        raise RuntimeError(f"rollback images remain unavailable: {still_missing}")

    command = [
        "docker", "compose", "--project-name", args.project_name,
        "--project-directory", str(project_directory),
        "--env-file", str(env_file),
        "-f", str(compose_file), "-f", str(override_file),
    ]
    run([*command, "stop", *services])
    run([*command, "up", "-d", "--no-build", "--no-deps", "--force-recreate", *services])
    wait_health(args.health_url, args.health_contains, args.health_timeout)
    print("application rollback completed and health check passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"rollback failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
