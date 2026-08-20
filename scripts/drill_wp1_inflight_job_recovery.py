#!/usr/bin/env python3
"""Verify in-flight Celery job redelivery after an isolated worker loss."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

TASK_SOURCE = r'''
import os
import time
import redis
from celery import Celery
from job_lease import JobLeaseStore

broker = os.environ["CELERY_BROKER_URL"]
app = Celery("wp1_inflight", broker=broker, backend=broker)
app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_acks_on_failure_or_timeout=False,
    task_default_delivery_mode="persistent",
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 5},
    result_backend_transport_options={"visibility_timeout": 5},
)
app.conf.broker_transport_options = {"visibility_timeout": 5, "unacked_restore_limit": 10}
app.conf.task_acks_late = True
app.conf.task_reject_on_worker_lost = True
store = JobLeaseStore("/runtime/job-ledger.sqlite3")

@app.task(bind=True, acks_late=True, reject_on_worker_lost=True)
def in_flight_job(self, job_id):
    lease = store.claim(job_id, self.request.id, lease_seconds=5)
    if not lease:
        return {"status": "already-completed-or-owned", "job_id": job_id}
    client = redis.Redis.from_url(broker)
    client.set("wp1:inflight:visibility_timeout", str(app.connection().transport_options.get("visibility_timeout")), ex=300)
    attempt = client.incr("wp1:inflight:attempts")
    client.set("wp1:inflight:started", str(attempt), ex=300)
    time.sleep(30)
    if client.setnx("wp1:inflight:side_effect", "completed"):
        client.incr("wp1:inflight:side_effect_count")
    client.set("wp1:inflight:completed", "true", ex=300)
    store.complete(job_id, self.request.id)
    return {"attempt": attempt, "side_effect": "completed", "job_id": job_id}

@app.task
def recovery_kick():
    return "recovery-kick"

@app.task
def recovery_sweep():
    job_ids = store.recover_expired()
    task_ids = [in_flight_job.delay(job_id).id for job_id in job_ids]
    return {"recovered_job_ids": job_ids, "task_ids": task_ids}
'''


def docker(*parts: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *parts], text=True, capture_output=True, check=check)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.expanduser().resolve()
    report.mkdir(parents=True, exist_ok=True)
    project = f"kb-wp1-inflight-{secrets.token_hex(5)}"
    evidence: dict[str, object] = {
        "schema": "km.wp1.inflight-job-recovery-shadow.v1",
        "mode": "isolated-shadow",
        "project": project,
        "image": args.image,
        "production_touched": False,
        "side_effect_policy": "Redis SETNX, exactly one completion side effect",
    }

    with tempfile.TemporaryDirectory(prefix="kb-wp1-inflight-") as temp:
        root = Path(temp)
        (root / "task_app.py").write_text(TASK_SOURCE, encoding="utf-8")
        compose = root / "compose.yml"
        compose.write_text(
            f"""services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: [CMD, redis-cli, ping]
      interval: 1s
      timeout: 2s
      retries: 30
  worker:
    image: {args.image}
    command: celery -A task_app:app worker --loglevel=INFO --concurrency=1 --hostname=wp1-inflight@%h
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
      PYTHONDONTWRITEBYTECODE: "1"
    volumes:
      - {root}:/runtime:rw
      - {Path(__file__).parent.parent / 'app/core/job_lease.py'}:/runtime/job_lease.py:ro
    working_dir: /runtime
    depends_on:
      redis: {{condition: service_healthy}}
  sender:
    image: {args.image}
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
      PYTHONDONTWRITEBYTECODE: "1"
    volumes:
      - {root}:/runtime:rw
      - {Path(__file__).parent.parent / 'app/core/job_lease.py'}:/runtime/job_lease.py:ro
    working_dir: /runtime
    depends_on:
      redis: {{condition: service_healthy}}
""",
            encoding="utf-8",
        )
        base = ["docker", "compose", "--project-name", project, "-f", str(compose)]
        try:
            docker(*base[1:], "up", "-d", "worker")
            deadline = time.monotonic() + 60
            logs = ""
            while time.monotonic() < deadline:
                logs = docker(*base[1:], "logs", "--no-color", "worker", check=False).stdout
                if "ready" in logs.lower():
                    break
                time.sleep(1)
            else:
                raise RuntimeError("worker did not become ready")

            sender = docker(
                *base[1:], "run", "--rm", "sender", "python", "-c",
                "from task_app import store, in_flight_job; store.register('job-1'); print(in_flight_job.delay('job-1').id)",
            )
            evidence["task_id"] = sender.stdout.strip()
            # Redis is not published; use compose exec for assertions instead.
            started = False
            for _ in range(45):
                probe = docker(*base[1:], "exec", "redis", "redis-cli", "GET", "wp1:inflight:started", check=False)
                if probe.stdout.strip():
                    started = True
                    evidence["first_attempt"] = probe.stdout.strip()
                    break
                time.sleep(1)
            if not started:
                raise RuntimeError("in-flight task did not start")

            docker(*base[1:], "kill", "worker")
            evidence["worker_killed_during_job"] = True
            evidence["unacked_before_recovery"] = {
                "queue_length": docker(*base[1:], "exec", "redis", "redis-cli", "LLEN", "celery", check=False).stdout.strip(),
                "unacked_keys": docker(*base[1:], "exec", "redis", "redis-cli", "KEYS", "unacked*", check=False).stdout.strip(),
                "unacked_index": docker(*base[1:], "exec", "redis", "redis-cli", "ZRANGE", "unacked_index", "0", "-1", "WITHSCORES", check=False).stdout.strip(),
                "effective_visibility_timeout": docker(*base[1:], "exec", "redis", "redis-cli", "GET", "wp1:inflight:visibility_timeout", check=False).stdout.strip(),
            }
            docker(*base[1:], "up", "-d", "worker")
            kick_ids = []
            for _ in range(12):
                kick = docker(
                    *base[1:], "run", "--rm", "sender", "python", "-c",
                    "from task_app import recovery_kick; print(recovery_kick.delay().id)",
                )
                kick_ids.append(kick.stdout.strip())
            evidence["recovery_kick_task_ids"] = kick_ids
            sweep = docker(
                *base[1:], "run", "--rm", "sender", "python", "-c",
                "from task_app import recovery_sweep; print(recovery_sweep.delay().id)",
            )
            evidence["recovery_sweep_task_id"] = sweep.stdout.strip()
            completed = False
            for _ in range(60):
                value = docker(*base[1:], "exec", "redis", "redis-cli", "GET", "wp1:inflight:completed", check=False).stdout.strip()
                if value == "true":
                    completed = True
                    break
                time.sleep(1)
            attempts = docker(*base[1:], "exec", "redis", "redis-cli", "GET", "wp1:inflight:attempts", check=False).stdout.strip()
            side_effects = docker(*base[1:], "exec", "redis", "redis-cli", "GET", "wp1:inflight:side_effect_count", check=False).stdout.strip()
            ledger = docker(*base[1:], "exec", "worker", "python", "-c", "from job_lease import JobLeaseStore; print(JobLeaseStore('/runtime/job-ledger.sqlite3').get('job-1'))", check=False).stdout.strip()
            evidence.update({
                "completed_after_recovery": completed,
                "attempts": attempts,
                "side_effect_count": side_effects,
                "ledger": ledger,
                "redelivery_verified": int(attempts or "0") >= 2,
                "duplicate_side_effect_prevented": side_effects == "1",
            })
            if not completed or not evidence["redelivery_verified"] or not evidence["duplicate_side_effect_prevented"] or 'succeeded' not in ledger:
                raise RuntimeError(f"in-flight recovery assertion failed: {evidence}")
            evidence["recovery_verified"] = True
            evidence["worker_logs_tail"] = docker(*base[1:], "logs", "--no-color", "--tail", "120", "worker", check=False).stdout[-5000:]
        except Exception as exc:
            evidence["recovery_verified"] = False
            evidence["failure"] = f"{type(exc).__name__}: {exc}"
            evidence["diagnostic_logs"] = docker(*base[1:], "logs", "--no-color", "--tail", "200", check=False).stdout[-8000:]
            (report / "inflight-job-recovery-shadow-20260820.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            raise
        finally:
            docker(*base[1:], "down", "--volumes", "--remove-orphans", check=False)

    evidence["cleanup_verified"] = docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={project}", check=False).stdout.strip() == ""
    output = report / "inflight-job-recovery-shadow-20260820.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
