"""External test-report upload and KB review APIs."""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..test_reports.auth import authenticate_report_agent, authenticate_report_reviewer
from ..test_reports.excel_contract import ReportValidationError, parse_and_validate_report
from ..test_reports.registry import SubmissionConflict, SubmissionRegistry
from app.core.job_config import celery_headers


router = APIRouter()
MAX_PART_SIZE = int(os.getenv("KB_REPORT_MAX_PART_SIZE", str(200 * 1024 * 1024)))


class ReviewDecision(BaseModel):
    comment: str = Field(default="", max_length=2000)


def _registry() -> SubmissionRegistry:
    return SubmissionRegistry()


def _root() -> Path:
    root = Path(os.getenv("KB_REPORT_STAGING_ROOT", "/app/data/report-staging"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_name(value: str) -> str:
    name = Path(str(value or "")).name
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="檔名不合法")
    return name


def _public(item: dict) -> dict:
    return {key: value for key, value in item.items() if key != "original_path"}


@router.get("/api/agent/v1/health")
async def report_agent_health(request: Request):
    identity = authenticate_report_agent(request)
    _registry()
    return {"status": "ok", **identity, "schema_versions": ["1.0"]}


@router.post("/api/agent/v1/reports", status_code=202)
async def upload_report(request: Request):
    identity = authenticate_report_agent(request)
    form = await request.form(max_files=30, max_fields=50, max_part_size=MAX_PART_SIZE)
    report_file = form.get("file")
    if report_file is None:
        raise HTTPException(status_code=400, detail="缺少 file")
    report_name = _safe_name(report_file.filename)
    if Path(report_name).suffix.lower() != ".xlsx":
        raise HTTPException(status_code=422, detail={"errors": ["report 必須是 .xlsx 檔案"]})

    submission_id = f"report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    target_dir = _root() / submission_id
    target_dir.mkdir(parents=True, exist_ok=False)
    original_path = target_dir / report_name
    content = await report_file.read()
    await report_file.close()
    original_path.write_bytes(content)
    report_hash = hashlib.sha256(content).hexdigest()

    attachment_items: list[dict] = []
    attachment_dir = target_dir / "attachments"
    for attachment in form.getlist("attachments"):
        name = _safe_name(attachment.filename)
        payload = await attachment.read()
        await attachment.close()
        attachment_dir.mkdir(parents=True, exist_ok=True)
        path = attachment_dir / name
        path.write_bytes(payload)
        attachment_items.append({
            "name": name, "path": str(path), "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)
        })

    try:
        parsed = parse_and_validate_report(
            original_path, {item["name"]: item["sha256"] for item in attachment_items}
        )
    except ReportValidationError as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc

    manifest = parsed["manifest"]
    if manifest["environment"] != identity["environment"]:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=403, detail="報告 environment 與 Agent token 不符")
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if idempotency_key and idempotency_key != manifest["run_id"]:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Idempotency-Key 必須等於 Manifest.run_id")

    try:
        item, duplicate = _registry().create({
            "submission_id": submission_id, "environment": manifest["environment"],
            "run_id": manifest["run_id"], "agent_id": identity["agent_id"],
            "report_name": report_name, "report_hash": report_hash, "status": "pending_review",
            "original_path": str(original_path), "attachments": attachment_items, "manifest": manifest,
            "validation": {"valid": True, "schema_version": manifest["schema_version"]},
        })
    except SubmissionConflict as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise HTTPException(status_code=409, detail="run_id_conflict") from exc
    if duplicate:
        shutil.rmtree(target_dir, ignore_errors=True)
    return {**_public(item), "duplicate": duplicate}


@router.get("/api/agent/v1/reports/{submission_id}")
async def get_agent_report(submission_id: str, request: Request):
    identity = authenticate_report_agent(request)
    registry = _registry()
    item = registry.get(submission_id)
    if not item or item["agent_id"] != identity["agent_id"]:
        raise HTTPException(status_code=404, detail="找不到 report submission")
    if item.get("ingest_task_id"):
        from .tasks import get_ingest_task_state
        task_state = get_ingest_task_state(item["ingest_task_id"])
        if task_state and task_state.get("status") != item["status"]:
            try:
                item = registry.sync_ingest_status(submission_id, task_state)
            except SubmissionConflict:
                item = registry.get(submission_id)
    return _public(item)


@router.get("/api/admin/v1/report-submissions")
async def list_report_submissions(request: Request, status: str | None = None, limit: int = 100):
    authenticate_report_reviewer(request)
    return {"items": [_public(item) for item in _registry().list(status=status, limit=limit)]}


@router.get("/api/admin/v1/report-submissions/{submission_id}")
async def get_report_submission(submission_id: str, request: Request):
    authenticate_report_reviewer(request)
    item = _registry().get(submission_id)
    if not item:
        raise HTTPException(status_code=404, detail="找不到 report submission")
    return _public(item)


@router.get("/api/admin/v1/report-submissions/{submission_id}/download")
async def download_report_submission(submission_id: str, request: Request):
    authenticate_report_reviewer(request)
    item = _registry().get(submission_id)
    if not item:
        raise HTTPException(status_code=404, detail="找不到 report submission")
    path = Path(item["original_path"])
    if not path.is_file() or _root().resolve() not in path.resolve().parents:
        raise HTTPException(status_code=404, detail="report 檔案不存在")
    return FileResponse(path, filename=item["report_name"])


@router.post("/api/admin/v1/report-submissions/{submission_id}/approve")
async def approve_report_submission(submission_id: str, decision: ReviewDecision, request: Request):
    reviewer = authenticate_report_reviewer(request)
    registry = _registry()
    reviewed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        item = registry.transition(
            submission_id, {"pending_review"}, "approved", reviewer_id=reviewer["reviewer_id"],
            review_comment=decision.comment, reviewed_at=reviewed_at,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="找不到 report submission") from exc
    except SubmissionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    from .tasks import INGEST_UPLOAD_ROOT, create_ingest_task_id, ingest_file_task, set_ingest_task_state
    task_id = create_ingest_task_id()
    converted_path = INGEST_UPLOAD_ROOT / "Report" / task_id / "converted" / f"{Path(item['report_name']).stem}.md"
    try:
        converted_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        registry.transition(submission_id, {"approved"}, "ingest_failed", error=str(exc), ingest_task_id=task_id)
        raise HTTPException(status_code=503, detail=f"無法建立 ingest 目錄: {exc}") from exc
    state = {
        "task_id": task_id, "submission_id": submission_id, "file_name": item["report_name"],
        "original_path": item["original_path"], "converted_path": str(converted_path),
        "file_hash": item["report_hash"], "storage_category": "Report", "extraction_mode": "report",
        "attachments": item.get("attachments", []),
        "extraction_mode_name": "Test Report", "canonical_test_report": True, "status": "queued",
        "created_at": reviewed_at, "started_at": None, "finished_at": None, "error": None,
        "ingested": False, "content": "",
    }
    try:
        set_ingest_task_state(task_id, state)
        async_result = ingest_file_task.apply_async(
            args=[task_id],
            queue="ingest",
            headers=celery_headers(request.headers.get("x-trace-id")),
        )
        state["celery_task_id"] = async_result.id
        set_ingest_task_state(task_id, state)
        item = registry.transition(submission_id, {"approved"}, "queued", ingest_task_id=task_id)
    except Exception as exc:
        registry.transition(submission_id, {"approved"}, "ingest_failed", error=str(exc), ingest_task_id=task_id)
        raise HTTPException(status_code=503, detail=f"無法提交 ingest 任務: {exc}") from exc
    return _public(item)


@router.post("/api/admin/v1/report-submissions/{submission_id}/reject")
async def reject_report_submission(submission_id: str, decision: ReviewDecision, request: Request):
    reviewer = authenticate_report_reviewer(request)
    if not decision.comment.strip():
        raise HTTPException(status_code=422, detail="退回時必須填寫原因")
    try:
        item = _registry().transition(
            submission_id, {"pending_review"}, "rejected", reviewer_id=reviewer["reviewer_id"],
            review_comment=decision.comment.strip(), reviewed_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="找不到 report submission") from exc
    except SubmissionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _public(item)
