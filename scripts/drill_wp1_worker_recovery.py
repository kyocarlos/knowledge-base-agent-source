#!/usr/bin/env python3
"""Run an isolated WP1 worker failure/restart recovery drill."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=check, text=True, capture_output=True)


def http_status(url: str, payload: bytes | None = None) -> tuple[int, str]:
    request = Request(url, data=payload, method="POST" if payload else "GET")
    if payload:
        request.add_header("Content-Type", "application/json")
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, response.read().decode("utf-8", "replace")[:500]
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")[:500]
    except (URLError, OSError) as exc:
        return 0, str(getattr(exc, "reason", exc))


def wait_for(url: str, timeout: int = 120) -> tuple[int, str]:
    deadline = time.monotonic() + timeout
    last = (0, "not ready")
    while time.monotonic() < deadline:
        last = http_status(url)
        if last[0] == 200:
            return last
        time.sleep(2)
    return last


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    project = f"kb-wp1-recovery-{int(time.time())}"
    port = 28000 + secrets.randbelow(1000)
    uid, gid = os.getuid(), os.getgid()
    report = args.report.expanduser().resolve()
    report.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, object] = {
        "schema": "km.wp1.worker-recovery-shadow.v1",
        "mode": "isolated-shadow",
        "project": project,
        "image": args.image,
        "http_port": port,
        "production_touched": False,
        "data_write_scope": "temporary docker volumes only",
    }

    with tempfile.TemporaryDirectory(prefix="kb-wp1-recovery-") as temp:
        root = Path(temp)
        data = root / "data"
        config = root / "config"
        data.mkdir()
        (data / "uploads").mkdir()
        config.mkdir()
        config_file = config / "config.yaml"
        config_file.write_text(
            "neo4j:\n  uri: bolt://neo4j:7687\n  user: neo4j\n  password: shadow-pass\n"
            "qdrant:\n  url: http://qdrant:6333\n",
            encoding="utf-8",
        )
        compose = root / "compose.yml"
        compose.write_text(
            f"""services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: [CMD, redis-cli, ping]
      interval: 2s
      timeout: 2s
      retries: 30
  neo4j:
    image: neo4j:latest
    pull_policy: never
    environment:
      NEO4J_AUTH: neo4j/shadow-pass
    healthcheck:
      test: [CMD-SHELL, /var/lib/neo4j/bin/cypher-shell -u neo4j -p shadow-pass 'RETURN 1']
      interval: 3s
      timeout: 3s
      retries: 60
  qdrant:
    image: qdrant/qdrant:latest
    pull_policy: never
  web:
    image: {args.image}
    user: "{uid}:{gid}"
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
    ports: ["127.0.0.1:{port}:8000"]
    environment: &app_env
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      REDIS_URL: redis://redis:6379/0
      REDIS_HOST: redis
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: shadow-pass
      QDRANT_URL: http://qdrant:6333
      KB_INGEST_UPLOAD_ROOT: /app/data/uploads
      KB_INGEST_REGISTRY_URL: sqlite:////app/data/ingestion-registry.sqlite3
      HOME: /app/data/home
    volumes: &app_volumes
      - {config}:/app/config:ro
      - {data}:/app/data
    depends_on:
      redis: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  ingest_worker:
    image: {args.image}
    user: "{uid}:{gid}"
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=1 -Q ingest
    environment: *app_env
    volumes: *app_volumes
    depends_on:
      redis: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
""",
            encoding="utf-8",
        )
        base = ["docker", "compose", "--project-name", project, "-f", str(compose)]
        try:
            run([*base, "up", "-d", "--no-build"])
            status, body = wait_for(f"http://127.0.0.1:{port}/health")
            evidence["initial_health"] = {"status": status, "body": body}
            if status != 200:
                raise RuntimeError(f"shadow health did not become ready: {status} {body}")

            initial_ps = run([*base, "ps", "--format", "json"]).stdout
            evidence["initial_services"] = initial_ps
            run([*base, "kill", "ingest_worker"])
            stopped_ps = run([*base, "ps", "--format", "json"], check=False).stdout
            evidence["after_failure_services"] = stopped_ps

            run([*base, "up", "-d", "--no-build", "ingest_worker"])
            deadline = time.monotonic() + 90
            recovered_ps = ""
            while time.monotonic() < deadline:
                recovered_ps = run([*base, "ps", "--format", "json"], check=False).stdout
                if '"Service":"ingest_worker"' in recovered_ps and '"State":"running"' in recovered_ps:
                    break
                time.sleep(2)
            else:
                raise RuntimeError("ingest_worker did not return to running state")
            logs = run([*base, "logs", "--no-color", "--tail", "120", "ingest_worker"], check=False).stdout
            evidence["after_recovery_services"] = recovered_ps
            evidence["worker_logs_tail"] = logs[-4000:]
            evidence["recovery_verified"] = True
        except Exception as exc:
            evidence["recovery_verified"] = False
            evidence["failure"] = f"{type(exc).__name__}: {exc}"
            evidence["diagnostic_ps"] = run([*base, "ps", "-a", "--format", "json"], check=False).stdout
            evidence["diagnostic_logs"] = run([*base, "logs", "--no-color", "--tail", "160"], check=False).stdout[-8000:]
            evidence["cleanup_verified"] = False
            (report / "worker-failure-recovery-shadow-20260820.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            raise
        finally:
            run([*base, "down", "--volumes", "--remove-orphans"], check=False)

    evidence["cleanup_verified"] = run(["docker", "ps", "-aq", "--filter", f"label=com.docker.compose.project={project}"], check=False).stdout.strip() == ""
    output = report / "worker-failure-recovery-shadow-20260820.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
