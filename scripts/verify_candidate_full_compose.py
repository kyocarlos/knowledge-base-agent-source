#!/usr/bin/env python3
"""Verify exact candidate identity across an isolated four-service Compose runtime."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml


METADATA = ("KM_GIT_COMMIT", "KM_RELEASE_ID", "KM_IMAGE_DIGEST", "KM_BUILD_TIMESTAMP")
APP_SERVICES = ("web", "search_worker", "ingest_worker", "beat")


def run(command: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, check=False, text=True, capture_output=capture)
    if result.returncode:
        details = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{details}")
    return result


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(url: str) -> tuple[int, dict[str, object]]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode(errors="replace")}


def wait_for_health(url: str) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if get_json(url)[0] == 200:
                return
        except (OSError, json.JSONDecodeError):
            pass
        time.sleep(2)
    raise RuntimeError(f"isolated candidate did not become healthy: {url}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--image", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--build-timestamp", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    source = args.source_root.resolve()
    image_id = run(["docker", "image", "inspect", args.image, "--format", "{{.Id}}"], capture=True).stdout.strip()
    if image_id != args.image_digest:
        raise SystemExit(f"candidate image identity mismatch: tag={image_id} expected={args.image_digest}")

    project = f"kb-wp0-full-compose-{int(time.time())}"
    port = free_port()
    uid, gid = os.getuid(), os.getgid()
    neo_password = secrets.token_urlsafe(24)
    report_password = secrets.token_urlsafe(24)
    ledger_path = "/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3"
    metadata = {
        "KM_GIT_COMMIT": args.commit,
        "KM_RELEASE_ID": args.release_id,
        "KM_IMAGE_DIGEST": args.image_digest,
        "KM_BUILD_TIMESTAMP": args.build_timestamp,
    }

    with tempfile.TemporaryDirectory(prefix="kb-wp0-full-compose-") as temp_name:
        temp = Path(temp_name)
        data = temp / "data"
        config = temp / "config"
        data.mkdir()
        (data / "uploads").mkdir()
        config.mkdir()
        config_values = yaml.safe_load((source / "config/config.yaml").read_text(encoding="utf-8"))
        config_values.setdefault("neo4j", {}).update({"uri": "bolt://neo4j:7687", "user": "neo4j", "password": neo_password})
        config_values.setdefault("qdrant", {})["url"] = "http://qdrant:6333"
        (config / "config.yaml").write_text(yaml.safe_dump(config_values, sort_keys=False), encoding="utf-8")
        env = {
            **metadata,
            "CELERY_BROKER_URL": "redis://redis:6379/0",
            "CELERY_RESULT_BACKEND": "redis://redis:6379/0",
            "REDIS_URL": "redis://redis:6379/0",
            "REDIS_HOST": "redis",
            "NEO4J_URI": "bolt://neo4j:7687",
            "NEO4J_USER": "neo4j",
            "NEO4J_PASSWORD": neo_password,
            "QDRANT_URL": "http://qdrant:6333",
            "KB_REPORT_REGISTRY_URL": f"postgresql://kb_report:{report_password}@report_registry:5432/kb_reports",
            "KB_INGEST_UPLOAD_ROOT": "/app/data/uploads",
            "KB_INGEST_REGISTRY_URL": "sqlite:////home/da40_ai_gb10/knowledge-base/data/ingestion-registry.sqlite3",
            "KB_JOB_LEDGER_PATH": ledger_path,
            "CELERYBEAT_SCHEDULE_FILENAME": "/home/da40_ai_gb10/knowledge-base/data/celerybeat-schedule",
            "HOME": "/app/data/home",
        }
        environment = "\n".join(f"      {key}: {value!r}" for key, value in env.items())
        compose = temp / "compose.yml"
        compose.write_text(
            f"""services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: [CMD, redis-cli, ping]
      interval: 2s
      timeout: 2s
      retries: 30
  report_registry:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: kb_reports
      POSTGRES_USER: kb_report
      POSTGRES_PASSWORD: {report_password}
    healthcheck:
      test: [CMD-SHELL, pg_isready -U kb_report -d kb_reports]
      interval: 2s
      timeout: 2s
      retries: 30
  neo4j:
    image: neo4j:latest
    environment:
      NEO4J_AUTH: neo4j/{neo_password}
      NEO4J_PLUGINS: '["apoc"]'
    healthcheck:
      test: ["CMD-SHELL", "exit 0"]
      interval: 3s
      timeout: 3s
      retries: 60
  qdrant:
    image: qdrant/qdrant:latest
  web:
    image: {args.image}
    user: "{uid}:{gid}"
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
    ports: ["127.0.0.1:{port}:8000"]
    environment:
{environment}
    volumes:
      - {config}:/app/config:ro
      - {data}:/app/data
      - {data}:/home/da40_ai_gb10/knowledge-base/data
    depends_on:
      redis: {{condition: service_healthy}}
      report_registry: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  search_worker:
    image: {args.image}
    user: "{uid}:{gid}"
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=1 -Q search
    environment:
{environment}
    volumes:
      - {config}:/app/config:ro
      - {data}:/app/data
      - {data}:/home/da40_ai_gb10/knowledge-base/data
    depends_on:
      redis: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  ingest_worker:
    image: {args.image}
    user: "{uid}:{gid}"
    command: celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=1 -Q ingest
    environment:
{environment}
    volumes:
      - {config}:/app/config:ro
      - {data}:/app/data
      - {data}:/home/da40_ai_gb10/knowledge-base/data
    depends_on:
      redis: {{condition: service_healthy}}
      report_registry: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
  beat:
    image: {args.image}
    user: "{uid}:{gid}"
    command: celery -A src.web_api.tasks:celery_app beat --loglevel=info --schedule /home/da40_ai_gb10/knowledge-base/data/celerybeat-schedule
    environment:
{environment}
    volumes:
      - {config}:/app/config:ro
      - {data}:/app/data
      - {data}:/home/da40_ai_gb10/knowledge-base/data
    depends_on:
      redis: {{condition: service_healthy}}
      neo4j: {{condition: service_healthy}}
      qdrant: {{condition: service_started}}
""",
            encoding="utf-8",
        )
        command = ["docker", "compose", "--project-name", project, "-f", str(compose)]
        evidence: dict[str, object] = {
            "schema": "km.wp0.full-compose-metadata.v1",
            "project": project,
            "source_commit": args.commit,
            "release_id": args.release_id,
            "image": args.image,
            "image_digest": args.image_digest,
            "build_timestamp": args.build_timestamp,
            "production_touched": False,
            "secrets_included": False,
            "ledger_path": ledger_path,
        }
        try:
            rendered = json.loads(run([*command, "config", "--format", "json"], capture=True).stdout)
            evidence["rendered_service_images"] = {name: rendered["services"][name].get("image") for name in APP_SERVICES}
            evidence["rendered_metadata"] = {
                name: {key: rendered["services"][name]["environment"].get(key) for key in METADATA}
                for name in APP_SERVICES
            }
            for name in APP_SERVICES:
                service = rendered["services"].get(name, {})
                if service.get("image") != args.image:
                    raise RuntimeError(f"rendered image mismatch for {name}: {service.get('image')}")
                if any(service.get("environment", {}).get(key) != value for key, value in metadata.items()):
                    raise RuntimeError(f"rendered metadata mismatch for {name}")
            evidence["render_result"] = "PASS"
            run([*command, "up", "-d", "--no-build"])
            wait_for_health(f"http://127.0.0.1:{port}/health")
            container_evidence: dict[str, object] = {}
            for name in APP_SERVICES:
                container_id = run([*command, "ps", "-q", name], capture=True).stdout.strip()
                if not container_id:
                    exited_id = run([*command, "ps", "-aq", name], capture=True).stdout.strip()
                    diagnostic = "container was not created"
                    if exited_id:
                        state = json.loads(run(["docker", "inspect", exited_id], capture=True).stdout)[0]
                        logs = subprocess.run([*command, "logs", "--no-color", "--tail", "80", name], check=False, text=True, capture_output=True)
                        diagnostic = json.dumps({
                            "container_id": exited_id,
                            "status": state["State"],
                            "logs": (logs.stdout or logs.stderr)[-12000:],
                        }, ensure_ascii=False)
                    raise RuntimeError(f"missing running container for {name}: {diagnostic}")
                inspected = json.loads(run(["docker", "inspect", container_id], capture=True).stdout)[0]
                actual_env = dict(item.split("=", 1) for item in inspected["Config"]["Env"] if "=" in item)
                actual_mounts = [mount["Destination"] for mount in inspected["Mounts"]]
                container_evidence[name] = {
                    "container_id": container_id,
                    "image_id": inspected["Image"],
                    "running": inspected["State"]["Running"],
                    "metadata": {key: actual_env.get(key) for key in METADATA},
                    "ledger_path": actual_env.get("KB_JOB_LEDGER_PATH"),
                    "mounts": actual_mounts,
                }
                if inspected["Image"] != image_id or not inspected["State"]["Running"]:
                    raise RuntimeError(f"runtime image/state mismatch for {name}")
                if any(actual_env.get(key) != value for key, value in metadata.items()):
                    raise RuntimeError(f"runtime metadata mismatch for {name}")
                if actual_env.get("KB_JOB_LEDGER_PATH") != ledger_path or "/home/da40_ai_gb10/knowledge-base/data" not in actual_mounts:
                    raise RuntimeError(f"runtime ledger mount mismatch for {name}")
            status, version = get_json(f"http://127.0.0.1:{port}/api/v1/version")
            version_data = version.get("data", version)
            if not isinstance(version_data, dict):
                raise RuntimeError(f"runtime version payload is invalid: {version}")
            if status != 200 or any(version_data.get(key) != value for key, value in {
                "commit": args.commit,
                "release_id": args.release_id,
                "image_digest": args.image_digest,
                "build_timestamp": args.build_timestamp,
            }.items()):
                raise RuntimeError(f"runtime version mismatch: HTTP {status} {version}")
            evidence.update({"runtime_services": container_evidence, "version": {"status": status, **version}, "result": "PASS"})
        finally:
            subprocess.run([*command, "down", "--volumes", "--remove-orphans"], check=False, text=True, capture_output=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.output.chmod(0o600)
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
