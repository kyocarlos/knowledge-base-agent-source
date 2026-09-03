from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import ApiResponse


router = APIRouter(prefix="/metrics", tags=["Time-series metrics"])


class MetricWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    test_run_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime
    metric_name: str = Field(min_length=1, max_length=128)
    value: float
    unit: str = Field(min_length=1, max_length=32)
    package_id: str | None = Field(default=None, max_length=128)
    document_id: str | None = Field(default=None, max_length=256)


def _store():
    from src.timeseries_store import TimeSeriesStore

    return TimeSeriesStore()


@router.post("", response_model=ApiResponse[dict])
async def write_metric(payload: MetricWrite, request: Request):
    try:
        data = _store().write_metric(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Time-series store unavailable") from exc
    return ApiResponse(data=data, trace_id=request.state.trace_id)


@router.get("/{test_run_id}", response_model=ApiResponse[list[dict]])
async def query_metrics(test_run_id: str, request: Request, start: datetime | None = None, end: datetime | None = None):
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="start must not be after end")
    try:
        data = _store().query_metrics(test_run_id, start=start, end=end)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Time-series store unavailable") from exc
    return ApiResponse(data=data, trace_id=request.state.trace_id)
