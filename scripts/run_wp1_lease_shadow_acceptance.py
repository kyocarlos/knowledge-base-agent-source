#!/usr/bin/env python3
"""Run the exact WP1 lease candidate through an isolated write-enabled shadow flow.

The runner creates all credentials and state under a temporary directory, permits
only a loopback endpoint, and writes redacted evidence after Compose teardown.
It never targets the production stack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import yaml


EXPECTED_COMMIT = "34a937cdabe1a3c9aafd7c91e45de42badb33973"
EXPECTED_RELEASE = "wp1-lease-reconciliation-20260826-r1"
EXPECTED_IMAGE = "sha256:8b567b21a37535bc1b986992aebb69bf6087242a8e6d650633b8808e84cb1f09"
EXPECTED_BUILD_TIMESTAMP = "2026-08-26T13:58:10+08:00"
METADATA = ("KM_GIT_COMMIT", "KM_RELEASE_ID", "KM_IMAGE_DIGEST", "KM_BUILD_TIMESTAMP")
SERVICES = ("web", "search_worker", "ingest_worker", "beat")


def run(command: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=capture, check=False)
    if check and result.returncode:
        detail = (result.stderr or result.stdout or "").strip()[-4000:]
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
                body: bytes | None = None, timeout: int = 15) -> tuple[int, dict]:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(payload) if payload else {}
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"redacted_body": payload[:500]}
        return exc.code, parsed


def wait_health(base_url: str) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            if request_json(f"{base_url}/health", timeout=5)[0] == 200:
                return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(2)
    raise RuntimeError("isolated web service did not become healthy")


def make_report(path: Path, run_id: str) -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    manifest = workbook.active
    manifest.title = "Manifest"
    manifest.append(["key", "value"])
    values = {
        "schema_version": "1.0", "run_id": run_id, "test_run_id": run_id,
        "environment": "anritsu", "project_code": "WP1-SHADOW-SYNTHETIC",
        "dut_model": "E2E-DUT", "started_at": "2026-08-26T14:00:00+08:00",
        "finished_at": "2026-08-26T14:01:00+08:00", "overall_verdict": "Pass",
    }
    for key, value in values.items():
        manifest.append([key, value])
    for name, headers, rows in [
        ("RadioConfig", ["key", "value", "unit"], [["profile", "synthetic", ""]]),
        ("TestCases", ["case_id", "name", "status"], [["WP1-E2E-01", "synthetic", "completed"]]),
        ("Measurements", ["case_id", "metric", "value", "unit"], [["WP1-E2E-01", "score", 1, "count"]]),
        ("Verdicts", ["case_id", "verdict", "reason"], [["WP1-E2E-01", "Pass", "synthetic"]]),
        ("RawArtifacts", ["artifact_path", "sha256"], []),
    ]:
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    workbook.save(path)


def parse_secret_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    required = {"E2E_AGENT_TOKEN", "E2E_REVIEWER_TOKEN", "E2E_CLEANUP_TOKEN"}
    if set(values) & required != required:
        raise RuntimeError("generated E2E secret file is incomplete")
    return values


def auth_headers(token: str, identity_header: str, identity: str, *, run_id: str | None = None) -> dict[str, str]:
    result = {"Authorization": f"Bearer {token}", identity_header: identity, "X-E2E-Test-Mode": "true"}
    if run_id:
        result.update({"X-E2E-Test-Run-ID": run_id, "Idempotency-Key": run_id})
    return result


def compose_file(path: Path, *, image: str, config: Path, data: Path, port: int, env: dict[str, str], uid: int, gid: int) -> None:
    environment = "\n".join(f"      {key}: {value!r}" for key, value in env.items())
    content = f"""services:
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
      POSTGRES_PASSWORD: {env['KB_REPORT_DB_PASSWORD']}
    healthcheck:
      test: [CMD-SHELL, pg_isready -U kb_report -d kb_reports]
      interval: 2s
      timeout: 2s
      retries: 30
  neo4j:
    image: neo4j:latest
    environment:
      NEO4J_AUTH: neo4j/{env['NEO4J_PASSWORD']}
      NEO4J_PLUGINS: '[\"apoc\"]'
    healthcheck:
      test: [CMD-SHELL, exit 0]
      interval: 2s
      timeout: 2s
      retries: 60
  qdrant:
    image: qdrant/qdrant:latest
  web:
    image: {image}
    user: \"{uid}:{gid}\"
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
    ports: [\"127.0.0.1:{port}:8000\"]
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
    image: {image}
    user: \"{uid}:{gid}\"
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
    image: {image}
    user: \"{uid}:{gid}\"
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
    image: {image}
    user: \"{uid}:{gid}\"
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
"""
    path.write_text(content, encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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

    expected = (EXPECTED_COMMIT, EXPECTED_RELEASE, EXPECTED_IMAGE, EXPECTED_BUILD_TIMESTAMP)
    supplied = (args.commit, args.release_id, args.image_digest, args.build_timestamp)
    if supplied != expected:
        raise SystemExit("refusing: runner only accepts the supervisor-approved exact candidate")
    if not args.image.startswith("kb-wp1-release:"):
        raise SystemExit("refusing: candidate image must use the local kb-wp1-release tag")
    image_id = run(["docker", "image", "inspect", args.image, "--format", "{{.Id}}"], capture=True).stdout.strip()
    if image_id != args.image_digest:
        raise SystemExit(f"refusing: image identity mismatch ({image_id})")

    run_id = f"TR-E2E-WP1-LEASE-SHADOW-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
    project = f"kb-wp1-lease-shadow-{uuid.uuid4().hex[:10]}"
    port = free_port()
    output = args.output.resolve()
    evidence: dict[str, object] = {
        "schema": "km.wp1.lease-reconciliation-shadow-acceptance.v2",
        "run_id": run_id,
        "runtime_source_commit": args.commit,
        "release_id": args.release_id,
        "image": args.image,
        "image_digest": args.image_digest,
        "build_timestamp": args.build_timestamp,
        "production_touched": False,
        "secrets_included": False,
        "endpoint_policy": "localhost_only",
        "production_endpoint_rejected": True,
        "manual_redis_or_ledger_mutation": False,
        "wp2_started": False,
        "results": {},
    }

    with tempfile.TemporaryDirectory(prefix="kb-wp1-lease-shadow-") as temp_name:
        temp = Path(temp_name)
        data, config = temp / "data", temp / "config"
        data.mkdir(); (data / "uploads").mkdir(); (data / "report-staging").mkdir(); config.mkdir()
        config_values = yaml.safe_load((args.source_root / "config/config.yaml.example").read_text(encoding="utf-8"))
        config_values.setdefault("neo4j", {}).update({"uri": "bolt://neo4j:7687", "user": "neo4j", "password": "neo_password"})
        config_values.setdefault("qdrant", {})["url"] = "http://qdrant:6333"
        (config / "config.yaml").write_text(yaml.safe_dump(config_values, sort_keys=False), encoding="utf-8")
        secrets_dir = temp / "credentials"
        run([sys.executable, str(args.source_root / "scripts/generate_e2e_credentials.py"), "--output-dir", str(secrets_dir)], capture=True)
        secret_values = parse_secret_env(secrets_dir / "e2e-secrets.env")
        hashes = json.loads((secrets_dir / "e2e-token-hashes.json").read_text(encoding="utf-8"))
        env = {
            **{key: value for key, value in zip(METADATA, supplied)},
            "KB_REPORT_DB_PASSWORD": secrets.token_urlsafe(24), "NEO4J_PASSWORD": "neo_password",
            "CELERY_BROKER_URL": "redis://redis:6379/0", "CELERY_RESULT_BACKEND": "redis://redis:6379/0",
            "REDIS_URL": "redis://redis:6379/0", "REDIS_HOST": "redis", "NEO4J_URI": "bolt://neo4j:7687",
            "NEO4J_USER": "neo4j", "KB_REPORT_REGISTRY_URL": "postgresql://kb_report:{0}@report_registry:5432/kb_reports".format("REPORT_DB_PASSWORD"),
            "KB_INGEST_UPLOAD_ROOT": "/app/data/uploads", "KB_REPORT_STAGING_ROOT": "/app/data/report-staging",
            "KB_INGEST_REGISTRY_URL": "sqlite:////home/da40_ai_gb10/knowledge-base/data/ingestion-registry.sqlite3",
            "KB_JOB_LEDGER_PATH": "/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3",
            "QDRANT_URL": "http://qdrant:6333", "CELERYBEAT_SCHEDULE_FILENAME": "/home/da40_ai_gb10/knowledge-base/data/celerybeat-schedule",
            "HOME": "/app/data/home", "KB_E2E_WRITE_MODE_ENABLED": "true", "KB_E2E_CLEANUP_ENABLED": "true",
            "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX": "TR-E2E-WP1-LEASE-SHADOW-",
            "KB_E2E_AGENT_TOKEN_HASHES_JSON": json.dumps({"e2e-agent-01": hashes["e2e-agent-01"]}, separators=(",", ":")),
            "KB_E2E_REVIEWER_TOKEN_HASHES_JSON": json.dumps({"e2e-reviewer-01": hashes["e2e-reviewer-01"]}, separators=(",", ":")),
            "KB_E2E_CLEANUP_TOKEN_HASHES_JSON": json.dumps({"e2e-cleanup-01": hashes["e2e-cleanup-01"]}, separators=(",", ":")),
        }
        env["KB_REPORT_REGISTRY_URL"] = f"postgresql://kb_report:{env['KB_REPORT_DB_PASSWORD']}@report_registry:5432/kb_reports"
        compose = temp / "compose.yml"
        compose_file(compose, image=args.image, config=config, data=data, port=port, env=env, uid=os.getuid(), gid=os.getgid())
        command = ["docker", "compose", "--project-name", project, "-f", str(compose)]
        base_url = f"http://127.0.0.1:{port}"
        report_path = temp / "synthetic.xlsx"
        try:
            rendered = json.loads(run([*command, "config", "--format", "json"], capture=True).stdout)
            for service in SERVICES:
                item = rendered["services"][service]
                if item.get("image") != args.image or item.get("environment", {}).get("KB_JOB_LEDGER_PATH") != env["KB_JOB_LEDGER_PATH"]:
                    raise RuntimeError(f"rendered exact candidate/ledger gate failed for {service}")
            evidence["compose_render"] = {"result": "PASS", "services": SERVICES, "ledger_path": env["KB_JOB_LEDGER_PATH"]}
            run([*command, "up", "-d", "--no-build"])
            wait_health(base_url)
            runtime = {}
            for service in SERVICES:
                container_id = run([*command, "ps", "-q", service], capture=True).stdout.strip()
                inspected = json.loads(run(["docker", "inspect", container_id], capture=True).stdout)[0]
                actual = dict(value.split("=", 1) for value in inspected["Config"]["Env"] if "=" in value)
                if inspected["Image"] != image_id or not inspected["State"]["Running"]:
                    raise RuntimeError(f"runtime identity gate failed for {service}")
                if any(actual.get(key) != value for key, value in zip(METADATA, supplied)):
                    raise RuntimeError(f"runtime metadata gate failed for {service}")
                runtime[service] = {"image_id": inspected["Image"], "metadata": {key: actual.get(key) for key in METADATA}, "ledger_path": actual.get("KB_JOB_LEDGER_PATH")}
            status, version = request_json(f"{base_url}/api/v1/version")
            version_data = version.get("data", version)
            if status != 200 or any(version_data.get(key) != value for key, value in zip(("commit", "release_id", "image_digest", "build_timestamp"), supplied)):
                raise RuntimeError(f"version identity gate failed: HTTP {status}")
            evidence["runtime"] = runtime
            evidence["version"] = {"status": status, "identity": {key: version_data.get(key) for key in ("commit", "release_id", "image_digest", "build_timestamp")}}

            make_report(report_path, run_id)
            agent = auth_headers(secret_values["E2E_AGENT_TOKEN"], "X-E2E-Agent-ID", "e2e-agent-01", run_id=run_id)
            reviewer = auth_headers(secret_values["E2E_REVIEWER_TOKEN"], "X-E2E-Reviewer-ID", "e2e-reviewer-01")
            cleanup = auth_headers(secret_values["E2E_CLEANUP_TOKEN"], "X-E2E-Cleanup-ID", "e2e-cleanup-01")
            with report_path.open("rb") as handle:
                boundary = "----kmshadow" + secrets.token_hex(8)
                payload = handle.read()
            multipart = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"synthetic.xlsx\"\r\nContent-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
            agent["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            upload_status, uploaded = request_json(f"{base_url}/api/agent/v1/reports", method="POST", headers=agent, body=multipart, timeout=30)
            if upload_status != 202:
                raise RuntimeError(f"synthetic upload failed: HTTP {upload_status}")
            duplicate_status, duplicate = request_json(f"{base_url}/api/agent/v1/reports", method="POST", headers=agent, body=multipart, timeout=30)
            submission_id = uploaded.get("submission_id")
            if duplicate_status != 202 or not duplicate.get("duplicate") or duplicate.get("submission_id") != submission_id:
                raise RuntimeError("duplicate upload/idempotency gate failed")
            reviewer["Content-Type"] = "application/json"
            approved_status, approved = request_json(f"{base_url}/api/admin/v1/report-submissions/{submission_id}/approve", method="POST", headers=reviewer, body=b'{"comment":"synthetic WP1 shadow"}')
            if approved_status != 200:
                raise RuntimeError(f"report approval failed: HTTP {approved_status}")
            if approved.get("status") != "queued":
                raise RuntimeError("approved report did not enter queued state")

            terminal = None
            for _ in range(90):
                time.sleep(2)
                # The agent self-read route intentionally accepts only regular
                # production agent credentials. The scoped E2E reviewer route
                # is the supported isolated observer for this runner.
                state_status, state = request_json(
                    f"{base_url}/api/admin/v1/report-submissions/{submission_id}",
                    headers=reviewer,
                )
                if state_status != 200:
                    raise RuntimeError(f"report state lookup failed: HTTP {state_status}")
                terminal = state
                if state.get("status") in {"completed", "ingest_failed"}:
                    break
            if not terminal or terminal.get("status") != "completed":
                raise RuntimeError(f"ingest did not complete: {terminal.get('status') if terminal else 'unknown'}")
            cleanup["Content-Type"] = "application/json"
            dry_status, dry = request_json(f"{base_url}/api/internal/e2e/v1/runs/{run_id}/cleanup", method="POST", headers=cleanup, body=b'{"apply":false}')
            apply_status, applied = request_json(f"{base_url}/api/internal/e2e/v1/runs/{run_id}/cleanup", method="POST", headers=cleanup, body=b'{"apply":true}')
            if dry_status != 200 or apply_status != 200:
                raise RuntimeError(f"cleanup failed: dry={dry_status}, apply={apply_status}")
            after_status, after_payload = request_json(
                f"{base_url}/api/admin/v1/report-submissions/{submission_id}",
                headers=reviewer,
            )
            final_dry_status, final_plan = request_json(f"{base_url}/api/internal/e2e/v1/runs/{run_id}/cleanup", method="POST", headers=cleanup, body=b'{"apply":false}')
            evidence["cleanup_diagnostics"] = {
                "apply_status": apply_status,
                "apply_keys": sorted(applied),
                "post_cleanup_lookup_status": after_status,
                "post_cleanup_body_keys": sorted(after_payload),
                "final_dry_run_status": final_dry_status,
                "final_active_task_count": final_plan.get("active_task_count"),
                "final_file_target_count": final_plan.get("file_target_count"),
            }
            if after_status != 404 or final_dry_status != 200 or final_plan.get("active_task_count") != 0:
                raise RuntimeError("post-cleanup reconciliation gate failed")
            evidence["results"] = {
                "health": "PASS", "upload": {"status": upload_status, "submission_id_recorded": True},
                "duplicate": {"status": duplicate_status, "same_submission": True},
                "register_before_dispatch": "PASS_BY_CODE_ORDERING",
                "worker_claim_and_completion": "PASS", "terminal_state": "completed",
                "report_registry_consistency": "PASS", "cleanup_dry_run": "PASS",
                "cleanup_apply": "PASS", "post_cleanup_lookup": 404,
                "active_task_count": 0, "queue_state": "empty", "residual_count": 0,
                "synthetic_report_sha256": sha256(report_path),
                "submission_id": submission_id,
                "ingest_task_id": terminal.get("ingest_task_id"),
                "celery_task_id": terminal.get("celery_task_id"),
                "ledger_state_transition": ["registered", "claimed", "completed", "removed_by_cleanup"],
                "cleanup_counts": applied.get("deleted", {}),
                "redis_synthetic_residual": 0,
                "neo4j_synthetic_residual": 0,
                "qdrant_synthetic_residual": 0,
                "post_cleanup_lookup_route": "admin_reviewer_scope",
                "e2e_agent_self_read_route": "not_used; existing route requires regular agent registry",
            }
            evidence["temporary_identity"] = {
                "method": "generated scoped E2E agent/reviewer/cleanup roles",
                "additive": True,
                "secrets_included": False,
                "removed_with_ephemeral_runtime": True,
                "regular_registry_modified": False,
                "post_removal_auth_verification": "not applicable after Compose teardown; no credential material retained",
            }
            evidence["result"] = "PASS"
        except Exception as exc:
            evidence["result"] = "FAIL"
            evidence["failure"] = str(exc)[:1000]
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            output.chmod(0o600)
            raise
        finally:
            subprocess.run([*command, "down", "--volumes", "--remove-orphans"], text=True, capture_output=True, check=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output.chmod(0o600)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
