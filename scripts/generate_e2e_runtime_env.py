#!/usr/bin/env python3
"""Create a shell-safe, temporary E2E runtime env from hash-only credentials."""

from __future__ import annotations

import argparse
import json
import os
import shlex
from pathlib import Path


ROLES = {
    "agent": "e2e-agent-01",
    "reviewer": "e2e-reviewer-01",
    "cleanup": "e2e-cleanup-01",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hash-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id-prefix", required=True)
    args = parser.parse_args()

    hashes = json.loads(args.hash_file.read_text(encoding="utf-8"))
    if set(hashes) != set(ROLES.values()):
        raise ValueError("hash file must contain exactly the three E2E roles")

    values = {
        "KB_E2E_WRITE_MODE_ENABLED": "true",
        "KB_E2E_CLEANUP_ENABLED": "true",
        "KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX": args.run_id_prefix,
        "KB_E2E_AGENT_TOKEN_HASHES_JSON": json.dumps({ROLES["agent"]: hashes[ROLES["agent"]]}, separators=(",", ":")),
        "KB_E2E_REVIEWER_TOKEN_HASHES_JSON": json.dumps({ROLES["reviewer"]: hashes[ROLES["reviewer"]]}, separators=(",", ":")),
        "KB_E2E_CLEANUP_TOKEN_HASHES_JSON": json.dumps({ROLES["cleanup"]: hashes[ROLES["cleanup"]]}, separators=(",", ":")),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(f"{key}={shlex.quote(value)}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )
    os.chmod(args.output, 0o600)
    print(json.dumps({"output": str(args.output.resolve()), "mode": "0600", "run_id_prefix": args.run_id_prefix}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
