#!/usr/bin/env python3
"""Generate isolated E2E credentials without writing secrets to the repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path


ROLES = {
    "agent": ("e2e-agent-01", "anritsu", "report:upload"),
    "reviewer": ("e2e-reviewer-01", "", "report:review"),
    "cleanup": ("e2e-cleanup-01", "", "e2e:cleanup"),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(output_dir, 0o700)

    hashes: dict[str, dict] = {}
    secret_lines = ["# E2E-only secrets; do not commit or email this file"]
    for role, (identity, environment, scope) in ROLES.items():
        token = secrets.token_urlsafe(32)
        item = {"token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(), "scope": scope}
        if environment:
            item["environment"] = environment
        hashes[identity] = item
        secret_lines.append(f"E2E_{role.upper()}_ID={identity}")
        secret_lines.append(f"E2E_{role.upper()}_TOKEN={token}")

    hash_path = output_dir / "e2e-token-hashes.json"
    secret_path = output_dir / "e2e-secrets.env"
    hash_path.write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    secret_path.write_text("\n".join(secret_lines) + "\n", encoding="utf-8")
    os.chmod(hash_path, 0o600)
    os.chmod(secret_path, 0o600)
    print(json.dumps({"hash_file": str(hash_path), "secret_file": str(secret_path), "secret_file_mode": "0600"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
