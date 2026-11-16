"""RCA (root-cause analysis) endpoints for the product-verification zone.

    GET  /api/rca/v1/status               what this deployment can do (comparison always; analysis only when KM_RCA_ANALYZE=1)
    GET  /api/rca/v1/runs                 selectable reports (read-only, role filtered), with formula-error details
    POST /api/rca/v1/compare              deterministic comparison pack for 2..6 reports (no model, answers at once)
    POST /api/rca/v1/analyze              202 + task id: the model runs in a Celery worker, never in this web process
    GET  /api/rca/v1/analyze/{task_id}    running | done (pack + verified analysis) | failed; only the asker may read a finished result

Off unless KM_RCA_ENABLED=1. A KM login is required; the reports a caller may see are the ones whose access_roles intersect KM_RCA_ROLES
(default CSIT_ENGINEER, the role the report importer assigns). The model only ever sees the comparison pack, never the database.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..report_numeric import compare, query, rca_service

logger = logging.getLogger("km.rca")
ANALYZE_TASK = "tasks.rca_analyze_task"


class CompareRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=compare.MAX_RUNS)
    focus: dict | None = None  # band / bandwidth_mhz / direction: narrows what is compared and what the model sees


class AnalyzeRequest(CompareRequest):
    question: str = Field(default="", max_length=500)


class TaskQueue(Protocol):
    def submit(self, run_ids: list[str], question: str, owner: dict, focus: dict | None = None) -> str: ...
    def fetch(self, task_id: str) -> dict | None: ...   # None = not finished (or unknown); else the task's result dict


class CeleryTasks:
    """The analysis runs in the search worker (same queue as the Wi-Fi agent), so a slow model never occupies a web worker."""
    def submit(self, run_ids, question, owner, focus=None):
        from .tasks import celery_app
        return celery_app.send_task(ANALYZE_TASK, args=[run_ids, question, owner, focus], queue="search").id

    def fetch(self, task_id):
        from celery.result import AsyncResult
        from .tasks import celery_app
        result = AsyncResult(task_id, app=celery_app)
        if not result.ready():
            return None
        value = result.result
        return value if isinstance(value, dict) else {"status": "failed", "detail": "分析工作異常結束", "owner": None}


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


def _owner(identity: dict) -> dict:
    return {"user_id": identity["sub"], "instance_id": identity.get("instance_id")}


def default_roles() -> list[str]:
    return [r.strip() for r in os.getenv("KM_RCA_ROLES", "CSIT_ENGINEER").split(",") if r.strip()]


def default_connect():
    """A connection to the report store, opened per call so a missing or wrong setting is a 503 for RCA only, never a startup failure of the app."""
    import psycopg
    try:
        dsn = Path(os.environ["KM_RCA_DSN_FILE"]).read_text().strip() if os.getenv("KM_RCA_DSN_FILE") else os.environ["KM_RCA_DSN"]
        return psycopg.connect(dsn, autocommit=True, connect_timeout=5)
    except (KeyError, OSError, psycopg.Error):
        logger.warning("RCA report store unavailable", exc_info=True)
        raise HTTPException(status_code=503, detail="RCA report store is not available") from None


def default_llm() -> Callable[[list[dict]], str]:
    from .ollama_client import _build_primary_client
    from ..main import load_config
    client, _label = _build_primary_client(load_config())
    if client is None:
        raise RuntimeError("no primary LLM configured")
    # The shared default (60 s) suits short chat answers; an analysis of a large comparison needs longer. Only this task's own client is changed.
    client.timeout = float(os.getenv("KM_RCA_LLM_TIMEOUT_SECONDS", "300"))
    call = lambda messages: client.chat.completions.create(messages=messages, temperature=0).choices[0].message.content or ""
    call.client = client  # lets the task shorten a later call so the whole analysis stays inside its budget
    return call


def create_router(connect: Callable | None = None, tasks: TaskQueue | None = None, roles: Callable[[], list[str]] | None = None,
                  analyze_enabled: Callable[[], bool] | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/rca/v1", tags=["RCA"])
    connect_ = connect or default_connect
    roles_ = roles or default_roles
    queue = tasks or CeleryTasks()
    can_analyze = analyze_enabled or (lambda: tasks is not None or os.getenv("KM_RCA_ANALYZE") == "1")

    def _guard(request: Request) -> dict:
        identity = _identity(request)
        if os.getenv("KM_RCA_ENABLED") != "1" and connect is None:
            raise HTTPException(status_code=503, detail="RCA is not enabled")
        return identity

    def _pack(conn, run_ids: list[str], focus: dict | None = None) -> dict:
        try:
            return compare.compare_runs(compare.load_runs(conn, run_ids, roles_()), compare.load_directions(conn), focus=focus)
        except compare.CompareError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @router.get("/status")
    def status(request: Request):
        _guard(request)
        return {"compare": True, "analyze": bool(can_analyze())}

    @router.get("/runs")
    def list_runs(request: Request, product: str = "", report_type: str = ""):
        _guard(request)
        with connect_() as conn:
            rows = compare._rows(conn, """SELECT r.test_run_id, r.product_id, r.dut_model, r.report_type, r.technology, r.npi_stage, r.firmware_version, r.hardware_version,
                       r.chipset_vendor, r.test_date, r.overall_result, r.quality_status, r.formula_error_count, r.document_id, p.quality
                FROM km_test.test_run r LEFT JOIN km_test.report_package p USING (test_run_id)
                WHERE r.access_roles && %(roles)s AND r.publish_status = 'published' AND (%(p)s = '' OR r.product_id ILIKE %(l)s OR r.dut_model ILIKE %(l)s)
                  AND (%(t)s = '' OR r.report_type = %(t)s) ORDER BY r.product_id, r.test_date DESC NULLS LAST, r.report_type LIMIT 300""",
                {"roles": roles_(), "p": product, "l": "%" + product.replace("%", "").replace("_", r"\_") + "%", "t": report_type})
        for r in rows:
            r["test_date"] = r["test_date"].isoformat() if r["test_date"] else None
            r["error_summary"] = compare.error_summary(r.pop("quality"))
        return {"runs": rows, "report_types": sorted(query.REPORT_TYPES)}

    @router.post("/compare")
    def compare_endpoint(body: CompareRequest, request: Request):
        _guard(request)
        with connect_() as conn:
            return _pack(conn, body.run_ids, body.focus)

    @router.post("/analyze", status_code=202)
    def analyze(body: AnalyzeRequest, request: Request):
        identity = _guard(request)
        if not can_analyze():
            raise HTTPException(status_code=503, detail="RCA analysis is not enabled")
        with connect_() as conn:
            _pack(conn, body.run_ids, body.focus)  # an impossible selection fails here, at once, instead of after a queue wait
        try:
            task_id = queue.submit(body.run_ids, body.question.strip(), _owner(identity), body.focus)
        except Exception:  # noqa: BLE001 - broker down: the comparison still works
            logger.warning("RCA analysis could not be queued", exc_info=True)
            raise HTTPException(status_code=503, detail="分析佇列暫時無法使用") from None
        return {"task_id": task_id, "status": "submitted"}

    @router.get("/analyze/{task_id}")
    def analyze_result(task_id: str, request: Request):
        identity = _guard(request)
        try:
            value = queue.fetch(task_id)
        except Exception:  # noqa: BLE001
            logger.warning("RCA result lookup failed", exc_info=True)
            raise HTTPException(status_code=503, detail="分析結果暫時無法讀取") from None
        if value is None:
            return {"status": "running"}
        if value.get("owner") != _owner(identity):
            raise HTTPException(status_code=404, detail="task not found")
        return {k: v for k, v in value.items() if k != "owner"}

    return router
