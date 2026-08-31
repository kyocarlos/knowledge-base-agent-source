#!/usr/bin/env python3
"""Fail-closed uniqueness gate for production acceptance run IDs."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RUN_ID_PATTERNS = {
    "production": re.compile(r"^TR-E2E-WP1-PROD-[A-Za-z0-9._:-]+$"),
    "isolated": re.compile(r"^TR-E2E-WP1-GATEB-ISOLATED-[A-Za-z0-9._:-]+$"),
}
PRODUCTION_NAME_MARKERS = ("production-acceptance", "production_acceptance", "prod-acceptance")


def _run_ids(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"run_id", "test_run_id", "evidence_run_id"} and isinstance(item, str) and any(pattern.fullmatch(item) for pattern in RUN_ID_PATTERNS.values()):
                found.add(item)
            found.update(_run_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_run_ids(item))
    return found


def _is_production_attempt(path: Path, payload: object) -> bool:
    name = path.name.lower()
    if any(marker in name for marker in PRODUCTION_NAME_MARKERS):
        return True
    if not isinstance(payload, dict):
        return False
    return any(payload.get(key) is True for key in ("production_touched", "production_write_performed", "production_acceptance_started"))


def collect_prior_production_run_ids(evidence_root: Path) -> set[str]:
    """Read JSON evidence only; never modifies the evidence root."""
    if not evidence_root.is_dir():
        raise ValueError(f"production evidence root does not exist: {evidence_root}")
    found: set[str] = set()
    for path in sorted(evidence_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if _is_production_attempt(path, payload):
            found.update(_run_ids(payload))
    return found


def collect_prior_run_ids(evidence_root: Path, execution_mode: str) -> set[str]:
    """Read IDs for the selected lifecycle namespace without modifying it."""
    if execution_mode == "production":
        return collect_prior_production_run_ids(evidence_root)
    pattern = RUN_ID_PATTERNS.get(execution_mode)
    if pattern is None:
        raise ValueError("execution_mode must be production or isolated")
    if not evidence_root.is_dir():
        raise ValueError(f"evidence root does not exist: {evidence_root}")
    found: set[str] = set()
    for path in sorted(evidence_root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        found.update(item for item in _run_ids(payload) if pattern.fullmatch(item))
    return found


def check_unique_run_id(run_id: str, evidence_root: Path, execution_mode: str) -> dict[str, object]:
    pattern = RUN_ID_PATTERNS.get(execution_mode)
    if pattern is None:
        raise ValueError("execution_mode must be production or isolated")
    if not pattern.fullmatch(run_id):
        raise ValueError(f"run_id does not match the {execution_mode} E2E format")
    prior = sorted(collect_prior_run_ids(evidence_root, execution_mode))
    matched = run_id in prior
    result = {
        "run_id": run_id,
        "run_id_uniqueness_gate": "FAIL" if matched else "PASS",
        "prior_production_attempt_count": len(prior),
        "matched_prior_run_id": matched,
        "read_only": True,
        "network_or_write_started": False,
    }
    if matched:
        raise ValueError(json.dumps(result, sort_keys=True))
    return result


def check_unique_production_run_id(run_id: str, evidence_root: Path) -> dict[str, object]:
    return check_unique_run_id(run_id, evidence_root, "production")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--execution-mode", choices=tuple(RUN_ID_PATTERNS), default="production")
    args = parser.parse_args()
    try:
        print(json.dumps(check_unique_run_id(args.run_id, args.evidence_root.resolve(), args.execution_mode), indent=2))
    except (OSError, ValueError) as exc:
        print(f"run ID uniqueness gate failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
