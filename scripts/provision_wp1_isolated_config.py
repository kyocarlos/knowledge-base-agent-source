#!/usr/bin/env python3
"""Provision one temporary, protected config file for an isolated WP1 run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_production_path(path: Path, label: str) -> None:
    resolved = path.resolve()
    if str(resolved).startswith("/srv/knowledge-base-production-"):
        raise ValueError(f"{label} points at a production path")


def provision(source_config: Path, output_dir: Path, evidence_out: Path) -> dict[str, object]:
    if not source_config.is_file() or source_config.is_symlink() or not os.access(source_config, os.R_OK):
        raise ValueError("source config must be a readable regular file")
    _reject_production_path(output_dir, "isolated output")
    _reject_production_path(evidence_out, "evidence output")
    if output_dir.resolve() == source_config.resolve():
        raise ValueError("isolated output must differ from source config")

    output_dir.mkdir(parents=True, exist_ok=False)
    os.chmod(output_dir, 0o700)
    target = output_dir / "config.yaml"
    shutil.copyfile(source_config, target)
    os.chmod(target, 0o600)
    record = {
        "source_path": str(source_config.resolve()),
        "isolated_config_path": str(target.resolve()),
        "source_sha256": _sha256(source_config),
        "isolated_sha256": _sha256(target),
        "isolated_dir_mode": "700",
        "isolated_file_mode": "600",
        "execution_mode": "isolated",
        "secrets_included": False,
    }
    evidence_out.parent.mkdir(parents=True, exist_ok=True)
    evidence_out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    os.chmod(evidence_out, 0o640)
    return record


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-mode", required=True, choices=("isolated",))
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--evidence-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        record = provision(args.source_config, args.output_dir, args.evidence_out)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
