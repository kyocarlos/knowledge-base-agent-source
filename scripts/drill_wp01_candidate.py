#!/usr/bin/env python3
"""Run the WP0/WP1 candidate against isolated shadow dependencies."""

from __future__ import annotations

import argparse
import json
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import yaml


def run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, text=True, **kwargs)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def request(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def post_json(url: str, payload: dict[str, object], headers: dict[str, str] | None = None) -> tuple[int, str]:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")


def wait_http(url: str, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if request(url)[0] == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"candidate did not become healthy: {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--report-root", type=Path, default=Path.home() / "kb-pre-wp01-drills")
    args = parser.parse_args()

    source = args.source_root.resolve()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project = f"kb-wp01-candidate-{stamp.lower().replace('_', '-')}"
    prefix = project
    port = free_port()
    neo_password = secrets.token_urlsafe(24)
    report_password = secrets.token_urlsafe(24)
    report_dir = args.report_root.expanduser().resolve() / f"candidate-{stamp}"
    report_dir.mkdir(parents=True, mode=0o700)
    evidence: dict[str, object] = {"project": project, "image": args.image, "port": port}

    with tempfile.TemporaryDirectory(prefix="kb-wp01-candidate-") as temp:
        work = Path(temp)
        data_dir = work / "data"
        config_dir = work / "config"
        data_dir.mkdir()
        (data_dir / "uploads").mkdir()
        config_dir.mkdir()
        config = yaml.safe_load((source / "config/config.yaml").read_text())
        config.setdefault("neo4j", {})["uri"] = "bolt://neo4j:7687"
        config["neo4j"]["user"] = "neo4j"
        config["neo4j"]["password"] = neo_password
        config.setdefault("qdrant", {})["url"] = "http://qdrant:6333"
        (config_dir / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))

        compose = work / "compose.yml"
        compose.write_text(f"""services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: [\"CMD\", \"redis-cli\", \"ping\"]
      interval: 2s
      timeout: 2s
      retries: 30
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: kb_reports
      POSTGRES_USER: kb_report
      POSTGRES_PASSWORD: {report_password}
    healthcheck:
      test: [\"CMD-SHELL\", \"pg_isready -U kb_report -d kb_reports\"]
      interval: 2s
      timeout: 2s
      retries: 30
  neo4j:
    image: neo4j:latest
    pull_policy: never
    environment:
      NEO4J_AUTH: neo4j/{neo_password}
      NEO4J_PLUGINS: '[\"apoc\"]'
    healthcheck:
      test: [\"CMD-SHELL\", \"/var/lib/neo4j/bin/cypher-shell -u neo4j -p \\\"$${{NEO4J_AUTH#neo4j/}}\\\" 'RETURN 1'\"]
      interval: 3s
      timeout: 3s
      retries: 60
  qdrant:
    image: qdrant/qdrant:latest
    pull_policy: never
  web:
    image: {args.image}
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
    ports: [\"127.0.0.1:{port}:8000\"]
    environment: &app_env
      CELERY_BROKER_URL: redis://redis:6379/0
      CELERY_RESULT_BACKEND: redis://redis:6379/0
      REDIS_URL: redis://redis:6379/0
      REDIS_HOST: redis
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: {neo_password}
      QDRANT_URL: http://qdrant:6333
      KB_REPORT_REGISTRY_URL: postgresql://kb_report:{report_password}@postgres:5432/kb_reports
      KB_INGEST_UPLOAD_ROOT: /app/data/uploads
      KB_INGEST_REGISTRY_URL: sqlite:////app/data/ingestion-registry.sqlite3
    volumes: &app_volumes
      - {config_dir}:/app/config:ro
      - {data_dir}:/app/data
      - {data_dir}:/home/da40_ai_gb10/knowledge-base/data
    depends_on:
      redis: {{condition: service_healthy}}
      postgres: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  search_worker:
    image: {args.image}
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=1 -Q search
    environment: *app_env
    volumes: *app_volumes
    depends_on:
      redis: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  ingest_worker:
    image: {args.image}
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=1 -Q ingest
    environment: *app_env
    volumes: *app_volumes
    depends_on:
      redis: {{condition: service_healthy}}
      postgres: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  beat:
    image: {args.image}
    command: celery -A src.web_api.tasks:celery_app beat --loglevel=info
    environment: *app_env
    volumes: *app_volumes
    depends_on:
      redis: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
""")
        command = ["docker", "compose", "--project-name", project, "-f", str(compose)]
        try:
            run([*command, "up", "-d", "--no-build"])
            wait_http(f"http://127.0.0.1:{port}/health")
            probes = {}
            for path in ("/health", "/api/v1/health", "/api/v1/health/live", "/api/v1/health/ready", "/api/v1/version", "/api/agent/v1/health"):
                probes[path] = dict(zip(("status", "body"), request(f"http://127.0.0.1:{port}{path}")))
            expected = {
                "/health": 200, "/api/v1/health": 200, "/api/v1/health/live": 200,
                "/api/v1/health/ready": 200, "/api/v1/version": 200, "/api/agent/v1/health": 401,
            }
            if any(probes[path]["status"] != status for path, status in expected.items()):
                raise RuntimeError(f"candidate API contract mismatch: {probes}")
            search_status, search_body = post_json(
                f"http://127.0.0.1:{port}/search",
                {"query": "WP01 shadow search submission", "mode": "basic", "sources_only": True},
                {"X-Trace-ID": "wp01-shadow-trace"},
            )
            if search_status != 200 or not json.loads(search_body).get("task_id"):
                raise RuntimeError(f"candidate search submission failed: {search_status} {search_body}")
            running = {}
            for service in ("web", "search_worker", "ingest_worker", "beat"):
                container_id = subprocess.check_output([*command, "ps", "-q", service], text=True).strip()
                running[service] = subprocess.check_output(
                    ["docker", "inspect", container_id, "--format", "{{.State.Running}}"], text=True
                ).strip() == "true"
            if not all(running.values()):
                raise RuntimeError(f"candidate services are not all running: {running}")
            evidence.update({
                "probes": probes,
                "search_submission": {"status": search_status, "task_id_present": True},
                "services_running": running,
                "result": "passed",
            })
        finally:
            subprocess.run([*command, "down", "--volumes", "--remove-orphans"], check=False)
        evidence["finished_at"] = datetime.now(timezone.utc).isoformat()
        report = report_dir / "candidate-drill.json"
        report.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
        report.chmod(0o600)
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
