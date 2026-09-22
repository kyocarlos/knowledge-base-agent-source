"""Protected, bounded read API for KM Test Report time-series data."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request

from ..test_reports.auth import authenticate_reviewer
from ..timeseries_store import TimeseriesStore, TimeseriesValidationError

router = APIRouter(prefix="/api/v1/reports", tags=["test-report-timeseries"])


def _scope(project: str | None, role: str | None) -> str:
    if not project or not project.strip():
        raise HTTPException(status_code=401, detail="X-KM-Project scope is required")
    if role not in {"report-reader", "report-admin"}:
        raise HTTPException(status_code=403, detail="report read role is required")
    return project.strip()


def _store() -> TimeseriesStore:
    try:
        return TimeseriesStore()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="TimescaleDB is not configured") from exc


@router.get("/timeseries/runs")
def list_report_runs(request: Request,
                     project: str | None = Header(default=None, alias="X-KM-Project"),
                     role: str | None = Header(default=None, alias="X-KM-Role"),
                     limit: int = Query(default=50, ge=1, le=100)):
    authenticate_reviewer(request)
    return {"items": _store().list_runs(_scope(project, role), limit=limit)}


@router.get("/{run_id}/timeseries/summary")
def report_summary(request: Request, run_id: str, version: str, project: str | None = Header(default=None, alias="X-KM-Project"),
                   role: str | None = Header(default=None, alias="X-KM-Role")):
    authenticate_reviewer(request)
    scope = _scope(project, role)
    store = _store()
    run = store.get_run(run_id, scope, version)
    if not run:
        raise HTTPException(status_code=404, detail="published report run not found")
    return {"run": run, "items": store.get_summary(run_id, version, scope)}


@router.get("/{run_id}/timeseries/samples")
def report_samples(request: Request, run_id: str, version: str, metric: str | None = None,
                   start: str | None = None, end: str | None = None,
                   limit: int = Query(default=1000, ge=1, le=5000),
                   project: str | None = Header(default=None, alias="X-KM-Project"),
                   role: str | None = Header(default=None, alias="X-KM-Role")):
    try:
        authenticate_reviewer(request)
        scope = _scope(project, role)
        store = _store()
        if not store.get_run(run_id, scope, version):
            raise HTTPException(status_code=404, detail="published report run not found")
        items = store.get_samples(run_id, version, scope, metric=metric, start=start, end=end, limit=limit)
    except TimeseriesValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"run_id": run_id, "document_version": version, "metric": metric,
            "items": items, "count": len(items)}
