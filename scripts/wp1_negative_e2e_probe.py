#!/usr/bin/env python3
"""Prove that the same temporary E2E identity is fail-closed after restore."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_wp1_production_acceptance import post_multipart_observed, read_env


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--attachment", type=Path, required=True)
    parser.add_argument("--credentials-env", type=Path, required=True)
    parser.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args()
    secrets = read_env(args.credentials_env)
    headers = {
        "Authorization": f"Bearer {secrets['E2E_AGENT_TOKEN']}",
        "X-E2E-Agent-ID": secrets["E2E_AGENT_ID"],
        "X-E2E-Test-Mode": "true",
        "X-E2E-Test-Run-ID": args.run_id,
        "Idempotency-Key": args.run_id,
    }
    status, _, observation = post_multipart_observed(
        f"{args.base_url.rstrip('/')}/api/agent/v1/reports",
        args.fixture,
        args.attachment,
        headers,
    )
    result = {
        "status": status,
        "expected": 404,
        "fail_closed": status == 404,
        "observation": observation,
        "secrets_included": False,
    }
    args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0 if status == 404 else 1


if __name__ == "__main__":
    raise SystemExit(main())
