#!/usr/bin/env python3
"""Run an isolated Redis restart and SETNX idempotency drill."""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import time
from pathlib import Path

import redis


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = args.report.expanduser().resolve()
    report.mkdir(parents=True, exist_ok=True)
    name = f"kb-wp1-redis-{secrets.token_hex(5)}"
    port = 29000 + secrets.randbelow(800)
    evidence: dict[str, object] = {
        "schema": "km.wp1.redis-reconnect-idempotency-shadow.v1",
        "mode": "isolated-shadow",
        "production_touched": False,
        "container": name,
        "port": port,
    }

    def docker(*parts: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["docker", *parts], text=True, capture_output=True, check=check)

    def wait_client() -> redis.Redis:
        client = redis.Redis(host="127.0.0.1", port=port, decode_responses=True)
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if client.ping():
                    return client
            except redis.RedisError:
                time.sleep(1)
        raise RuntimeError("Redis did not become ready")

    try:
        docker("run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:6379", "redis:7-alpine")
        client = wait_client()
        client.flushdb()
        key = "wp1:shadow:idempotency:RUN-20260820-001"
        first = client.set(key, "accepted", nx=True, ex=300)
        evidence["initial_ping"] = True
        evidence["first_set_nx"] = bool(first)
        docker("restart", name)
        client = wait_client()
        evidence["post_restart_ping"] = bool(client.ping())
        evidence["value_after_restart"] = client.get(key)
        duplicate = client.set(key, "duplicate", nx=True, ex=300)
        evidence["duplicate_set_nx"] = bool(duplicate)
        evidence["idempotency_verified"] = evidence["value_after_restart"] == "accepted" and duplicate is None
        if not evidence["idempotency_verified"]:
            raise RuntimeError(f"Redis idempotency mismatch: {evidence}")
    finally:
        docker("rm", "-f", name, check=False)

    evidence["cleanup_verified"] = docker("ps", "-aq", "--filter", f"name=^{name}$", check=False).stdout.strip() == ""
    output = report / "redis-reconnect-idempotency-shadow-20260820.json"
    output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
