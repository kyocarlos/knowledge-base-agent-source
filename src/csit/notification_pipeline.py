"""Test-only CSIT notification adapter into the existing KM report ingest flow.

The notification transport remains deliberately small.  This adapter validates
an allowlisted fixture, creates the normal KM report submission/task state and
hands execution to the existing ingest worker.  It never writes a search store
directly.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .notification import AllowlistedFixtureResolver, NotificationError, NotificationEvent


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fixtures_from_env() -> dict[str, tuple[str, str]]:
    """Read a test-only fixture allowlist without accepting event supplied paths."""
    raw = os.getenv("KM_CSIT_NOTIFICATION_FIXTURES_JSON", "").strip()
    if not raw:
        return {}
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NotificationError("fixture_config_invalid", "fixture allowlist is invalid", 503) from exc
    if not isinstance(values, Mapping):
        raise NotificationError("fixture_config_invalid", "fixture allowlist is invalid", 503)
    fixtures: dict[str, tuple[str, str]] = {}
    for fixture_id, item in values.items():
        if not isinstance(item, Mapping):
            raise NotificationError("fixture_config_invalid", "fixture allowlist is invalid", 503)
        path, digest = str(item.get("path", "")), str(item.get("sha256", "")).lower()
        if not fixture_id or not path or len(digest) != 64:
            raise NotificationError("fixture_config_invalid", "fixture allowlist is invalid", 503)
        fixtures[str(fixture_id)] = (path, digest)
    return fixtures


class CsitAuthoritativePipeline:
    """Create an approved CSIT-owned submission and enqueue the existing worker."""

    def __init__(self, resolver: AllowlistedFixtureResolver, *, enqueue: Callable[..., Any] | None = None):
        self.resolver = resolver
        self.enqueue = enqueue

    def __call__(self, event: NotificationEvent, job_id: str) -> Mapping[str, Any]:
        path, digest = self.resolver.resolve(event)
        from ..test_reports.excel_contract import ReportValidationError, parse_and_validate_report
        from ..test_reports.registry import SubmissionConflict, SubmissionRegistry
        from ..web_api.tasks import INGEST_UPLOAD_ROOT, create_ingest_task_id, set_ingest_task_state

        try:
            parsed = parse_and_validate_report(path)
        except ReportValidationError as exc:
            raise NotificationError("report_validation_failed", "CSIT fixture failed KM report validation", 422) from exc
        manifest = parsed["manifest"]
        run_id, environment = str(manifest["run_id"]), str(manifest["environment"])
        submission_id = f"csit_{uuid.uuid4().hex}"
        staging_root = Path(os.getenv("KB_REPORT_STAGING_ROOT", "/app/data/report-staging"))
        target_dir = staging_root / submission_id
        target_dir.mkdir(parents=True, exist_ok=False)
        target = target_dir / path.name
        shutil.copyfile(path, target)
        registry = SubmissionRegistry()
        try:
            submission, duplicate = registry.create({
                "submission_id": submission_id,
                "source_system": "CSIT",
                "environment": environment,
                "run_id": run_id,
                "agent_id": "csit-notification-fixture",
                "report_name": path.name,
                "report_hash": digest,
                "status": "approved",
                "original_path": str(target),
                "attachments": [],
                "manifest": manifest,
                "validation": {"valid": True, "schema_version": manifest["schema_version"], "source": "csit-authoritative"},
            })
        except SubmissionConflict as exc:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise NotificationError("run_id_conflict", "KM already has a different report for this test run", 409) from exc
        if duplicate:
            shutil.rmtree(target_dir, ignore_errors=True)
            return {"success": True, "terminal": False, "job_id": submission.get("ingest_task_id") or job_id,
                    "stage": submission.get("status") or "queued", "duplicate": True}

        task_id = create_ingest_task_id()
        converted_path = INGEST_UPLOAD_ROOT / "Report" / task_id / "converted" / f"{path.stem}.md"
        package_id = "csit:" + hashlib.sha256(f"{event.document_id}:{event.document_version}".encode()).hexdigest()[:24]
        state = {
            "task_id": task_id, "submission_id": submission["submission_id"], "file_name": path.name,
            "original_path": str(target), "converted_path": str(converted_path), "file_hash": digest,
            "storage_category": "Report", "extraction_mode": "report", "extraction_mode_name": "Test Report",
            "canonical_test_report": True, "status": "queued", "created_at": _now(), "started_at": None,
            "finished_at": None, "error": None, "ingested": False, "content": "",
            "document_id": event.document_id, "document_version": event.document_version, "package_id": package_id,
            "source_system": "CSIT", "event_id": event.event_id, "correlation_id": event.correlation_id,
            "publish_status": "published", "is_current": True,
            "acl": {"project_code": manifest["project_code"], "source_system": "CSIT"},
        }
        try:
            converted_path.parent.mkdir(parents=True, exist_ok=True)
            set_ingest_task_state(task_id, state)
            from ..web_api.tasks import ingest_csit_notification_task
            enqueue = self.enqueue or ingest_csit_notification_task.apply_async
            result = enqueue(args=[task_id, str(os.getenv("KM_CSIT_NOTIFICATION_DB", "data/csit-notification.sqlite3")),
                                   "csit-proposed-source", event.event_id], queue="ingest")
            registry.transition(submission["submission_id"], {"approved"}, "queued", ingest_task_id=task_id)
            return {"success": True, "terminal": False, "job_id": getattr(result, "id", task_id) or task_id,
                    "stage": "queued", "required_stores": ["neo4j", "qdrant", "timescaledb"]}
        except Exception as exc:
            registry.transition(submission["submission_id"], {"approved"}, "ingest_failed", error=str(exc), ingest_task_id=task_id)
            raise NotificationError("pipeline_enqueue_failed", "KM ingest task could not be queued", 503) from exc


def build_configured_processor() -> CsitAuthoritativePipeline:
    fixtures = _fixtures_from_env()
    if not fixtures:
        raise NotificationError("fixture_config_missing", "CSIT test fixture allowlist is not configured", 503)
    return CsitAuthoritativePipeline(AllowlistedFixtureResolver(fixtures))
