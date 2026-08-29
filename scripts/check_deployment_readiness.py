#!/usr/bin/env python3
"""Bounded post-recreate readiness gate for backend and formal ingress."""

from __future__ import annotations

import argparse
import json
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def probe(url: str, *, allow_insecure_tls: bool = False, timeout: float = 5) -> dict[str, object]:
    is_https = url.lower().startswith("https://")
    tls_mode = "insecure" if is_https and allow_insecure_tls else "verify"
    try:
        context = ssl._create_unverified_context() if tls_mode == "insecure" else None
        with urllib.request.urlopen(url, timeout=timeout, context=context) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return {
                    "url": url,
                    "status": 0,
                    "http_status": response.status,
                    "content_type": content_type,
                    "error": "invalid_json",
                    "error_type": type(exc).__name__,
                    "tls_verification_mode": tls_mode,
                }
            return {
                "url": url,
                "status": response.status,
                "content_type": content_type,
                "json": payload,
                "tls_verification_mode": tls_mode,
            }
    except urllib.error.HTTPError as exc:
        return {
            "url": url,
            "status": exc.code,
            "content_type": exc.headers.get("Content-Type", ""),
            "error": "http_error",
            "error_type": type(exc).__name__,
            "tls_verification_mode": tls_mode,
        }
    except OSError as exc:
        return {
            "url": url,
            "status": 0,
            "content_type": "",
            "error": "transport_error",
            "error_type": type(exc).__name__,
            "error_reason": str(exc).splitlines()[0][:200],
            "tls_verification_mode": tls_mode,
        }


def version_matches(result: dict[str, object], expected: dict[str, str]) -> bool:
    payload = result.get("json")
    if not isinstance(payload, dict):
        return False
    data = payload.get("data", payload)
    return isinstance(data, dict) and all(data.get(key) == value for key, value in expected.items())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-base-url", required=True)
    parser.add_argument("--ingress-base-url", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=120)
    parser.add_argument("--interval-seconds", type=float, default=2)
    parser.add_argument(
        "--allow-insecure-ingress-tls",
        action="store_true",
        help="Use an explicit non-verifying TLS context for the formal HTTPS ingress only.",
    )
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-release-id")
    parser.add_argument("--expected-image-digest")
    parser.add_argument("--expected-build-timestamp")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected_values = {
        "commit": args.expected_commit,
        "release_id": args.expected_release_id,
        "image_digest": args.expected_image_digest,
        "build_timestamp": args.expected_build_timestamp,
    }
    supplied = [value is not None for value in expected_values.values()]
    if any(supplied) and not all(supplied):
        parser.error("all expected metadata values must be supplied together")
    expected = {key: value for key, value in expected_values.items() if value is not None}
    started = now()
    deadline = time.monotonic() + args.timeout_seconds
    attempts = 0
    first_success: dict[str, str | None] = {"direct": None, "ingress": None}
    last: dict[str, object] = {}
    while time.monotonic() <= deadline:
        attempts += 1
        direct_health = probe(args.direct_base_url.rstrip("/") + "/health")
        direct_version = probe(args.direct_base_url.rstrip("/") + "/api/v1/version")
        direct_ok = direct_health.get("status") == 200 and direct_version.get("status") == 200
        if expected:
            direct_ok = direct_ok and version_matches(direct_version, expected)
        if direct_ok and first_success["direct"] is None:
            first_success["direct"] = now()

        ingress_health = probe(
            args.ingress_base_url.rstrip("/") + "/health",
            allow_insecure_tls=args.allow_insecure_ingress_tls,
        )
        ingress_version = probe(
            args.ingress_base_url.rstrip("/") + "/api/v1/version",
            allow_insecure_tls=args.allow_insecure_ingress_tls,
        )
        ingress_ok = ingress_health.get("status") == 200 and ingress_version.get("status") == 200
        if expected:
            ingress_ok = ingress_ok and version_matches(ingress_version, expected)
        if ingress_ok and first_success["ingress"] is None:
            first_success["ingress"] = now()

        last = {
            "direct": {"health": direct_health, "version": direct_version, "passed": direct_ok},
            "ingress": {"health": ingress_health, "version": ingress_version, "passed": ingress_ok},
        }
        if direct_ok and ingress_ok:
            break
        time.sleep(args.interval_seconds)

    evidence = {
        "schema": "km.deployment-readiness.v1",
        "started_at": started,
        "completed_at": now(),
        "timeout_seconds": args.timeout_seconds,
        "retry_interval_seconds": args.interval_seconds,
        "ingress_tls_verification_mode": "insecure" if args.allow_insecure_ingress_tls else "verify",
        "attempts": attempts,
        "first_success_at": first_success,
        "expected_metadata": expected,
        "last_result": last,
        "result": "PASS" if first_success["direct"] and first_success["ingress"] else "FAIL",
        "production_touched": False,
        "secrets_included": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"result": evidence["result"], "attempts": attempts, "output": str(args.output)}))
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
