"""RCA (root-cause analysis) endpoints for the product-verification zone.

    GET  /api/rca/v1/runs      selectable reports (read-only, role filtered)
    POST /api/rca/v1/compare   deterministic comparison pack for 2..6 reports (no model)
    POST /api/rca/v1/analyze   the same pack plus a verified cause analysis from the model

Off unless KM_RCA_ENABLED=1. A KM login is required; the reports a caller may see are the ones whose access_roles intersect KM_RCA_ROLES
(default CSIT_ENGINEER, the role the report importer assigns). The model only ever sees the comparison pack, never the database.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..report_numeric import compare, query, rca

logger = logging.getLogger("km.rca")


class CompareRequest(BaseModel):
    run_ids: list[str] = Field(min_length=2, max_length=compare.MAX_RUNS)


class AnalyzeRequest(CompareRequest):
    question: str = Field(default="", max_length=500)


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


def default_roles() -> list[str]:
    return [r.strip() for r in os.getenv("KM_RCA_ROLES", "CSIT_ENGINEER").split(",") if r.strip()]


def default_connect() -> Callable:
    import psycopg
    dsn = Path(os.environ["KM_RCA_DSN_FILE"]).read_text().strip() if os.getenv("KM_RCA_DSN_FILE") else os.environ["KM_RCA_DSN"]
    return lambda: psycopg.connect(dsn, autocommit=True)


def default_llm() -> Callable[[list[dict]], str]:
    from .ollama_client import _build_primary_client
    from ..main import load_config
    client, _label = _build_primary_client(load_config())
    if client is None:
        raise HTTPException(status_code=503, detail="RCA 需要主要 LLM，目前未設定或無法建立")
    return lambda messages: client.chat.completions.create(messages=messages, temperature=0).choices[0].message.content or ""


def create_router(connect: Callable | None = None, llm_factory: Callable | None = None, roles: Callable[[], list[str]] | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/rca/v1", tags=["RCA"])
    connect_ = connect or default_connect()
    roles_ = roles or default_roles

    def _guard(request: Request) -> None:
        _identity(request)
        if os.getenv("KM_RCA_ENABLED") != "1" and connect is None:
            raise HTTPException(status_code=503, detail="RCA is not enabled")

    def _pack(conn, run_ids: list[str]) -> dict:
        try:
            runs = compare.load_runs(conn, run_ids, roles_())
            return compare.compare_runs(runs, compare.load_directions(conn))
        except compare.CompareError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

    @router.get("/runs")
    def list_runs(request: Request, product: str = "", report_type: str = ""):
        _guard(request)
        with connect_() as conn:
            rows = compare._rows(conn, """SELECT test_run_id, product_id, dut_model, report_type, technology, npi_stage, firmware_version, hardware_version, chipset_vendor,
                       test_date, overall_result, quality_status, document_id FROM km_test.test_run
                WHERE access_roles && %(roles)s AND publish_status = 'published' AND (%(p)s = '' OR product_id ILIKE %(l)s OR dut_model ILIKE %(l)s)
                  AND (%(t)s = '' OR report_type = %(t)s) ORDER BY product_id, test_date DESC NULLS LAST, report_type LIMIT 300""",
                {"roles": roles_(), "p": product, "l": "%" + product.replace("%", "").replace("_", r"\_") + "%", "t": report_type})
        for r in rows:
            r["test_date"] = r["test_date"].isoformat() if r["test_date"] else None
        return {"runs": rows, "report_types": sorted(query.REPORT_TYPES)}

    @router.post("/compare")
    def compare_endpoint(body: CompareRequest, request: Request):
        _guard(request)
        with connect_() as conn:
            return _pack(conn, body.run_ids)

    @router.post("/analyze")
    def analyze(body: AnalyzeRequest, request: Request):
        _guard(request)
        with connect_() as conn:
            pack = _pack(conn, body.run_ids)
        llm = (llm_factory or default_llm)()
        try:
            out = rca.run_rca(pack, llm, question=body.question.strip())
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - a model failure must not take the deterministic comparison away
            logger.warning("RCA model call failed", exc_info=True)
            out = {"status": "unavailable", "analysis": None, "violations": ["模型暫時無法使用"], "warnings": [], "attempts": 0}
        return {"pack": pack, "rca": out}

    return router
