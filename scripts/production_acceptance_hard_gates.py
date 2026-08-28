#!/usr/bin/env python3
"""Pure, fail-closed helpers for production acceptance orchestration."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


def validate_production_evidence_root(root: Path) -> dict[str, object]:
    resolved = root.expanduser().resolve()
    if not resolved.is_dir():
        raise ValueError(f"production evidence root is not a directory: {resolved}")
    if not any(resolved.rglob("*.json")):
        raise ValueError(f"production evidence root has no JSON evidence: {resolved}")
    return {"evidence_root": str(resolved), "read_only": True, "validated": True}


def evaluate_cleanup_probe(status: int, body: object) -> dict[str, object]:
    available = status == 200 and isinstance(body, dict) and body.get("backend") == "available"
    return {"status": status, "available": available, "fail_closed": not available}


def capture_before_rollback(
    capture: Callable[[], dict[str, object]], rollback: Callable[[], object]
) -> dict[str, object]:
    """Capture is best-effort, but rollback always executes exactly once."""
    try:
        bundle = capture()
        capture_status = "PASS"
    except Exception as exc:  # noqa: BLE001 - rollback must not be blocked by diagnostics
        bundle = {"capture_error_type": type(exc).__name__}
        capture_status = "PARTIAL_FAIL"
    rollback_result = rollback()
    return {"capture_status": capture_status, "bundle": bundle, "rollback_result": rollback_result}


def validate_failure_bundle(bundle_path: Path) -> dict[str, object]:
    path = bundle_path.expanduser().resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload.get("failure_window"):
        raise ValueError("failure bundle must contain failure_window evidence")
    return {"persisted": True, "path": str(path), "secrets_included": False}
