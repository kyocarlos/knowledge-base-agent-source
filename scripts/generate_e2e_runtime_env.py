#!/usr/bin/env python3
"""Create a shell-safe, temporary E2E runtime env from hash-only credentials."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from production_run_id_gate import RUN_ID_PATTERNS

ROLES = {
    "agent": "e2e-agent-01",
    "reviewer": "e2e-reviewer-01",
    "cleanup": "e2e-cleanup-01",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hash-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--execution-mode", required=True, choices=tuple(RUN_ID_PATTERNS))
    parser.add_argument("--run-id-prefix", required=True)
    args = parser.parse_args()

    run_id_pattern = RUN_ID_PATTERNS[args.execution_mode]
    if not run_id_pattern.fullmatch(args.run_id_prefix):
        raise ValueError(f"run ID does not match the {args.execution_mode} E2E format")
    if not args.hash_file.is_file() or args.hash_file.is_symlink() or not os.access(args.hash_file, os.R_OK):
        raise ValueError("protected hash file must be a readable regular file")
    output = args.output.resolve()
    if str(output).startswith("/srv/knowledge-base-production-"):
        raise ValueError("overlay output cannot point at a production path")
    if args.execution_mode == "isolated" and any(
        marker in output.parts for marker in ("production-acceptance", "production_acceptance")
    ):
        raise ValueError("isolated overlay cannot use a production evidence namespace")
    if output.exists():
        raise ValueError("overlay output already exists")
    hashes = json.loads(args.hash_file.read_text(encoding="utf-8"))
    if not isinstance(hashes, dict):
        raise ValueError("hash file must contain an object")
    if set(hashes) != set(ROLES.values()):
        raise ValueError("hash file must contain exactly the three E2E roles")
    if any(
        not isinstance(value, dict)
        or not isinstance(value.get("token_sha256"), str)
        or not value["token_sha256"]
        for value in hashes.values()
    ):
        raise ValueError("hash file contains an invalid role value")

    values = {
        "KB_E2E_WRITE_MODE_ENABLED": "true",
        "KB_E2E_CLEANUP_ENABLED": "true",
        "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX": args.run_id_prefix,
        "KB_E2E_AGENT_TOKEN_HASHES_JSON": json.dumps({ROLES["agent"]: hashes[ROLES["agent"]]}, separators=(",", ":")),
        "KB_E2E_REVIEWER_TOKEN_HASHES_JSON": json.dumps({ROLES["reviewer"]: hashes[ROLES["reviewer"]]}, separators=(",", ":")),
        "KB_E2E_CLEANUP_TOKEN_HASHES_JSON": json.dumps({ROLES["cleanup"]: hashes[ROLES["cleanup"]]}, separators=(",", ":")),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(f"{key}={shlex.quote(value)}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    os.chmod(output, 0o600)
    print(json.dumps({"output": str(output), "mode": "0600", "execution_mode": args.execution_mode}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
