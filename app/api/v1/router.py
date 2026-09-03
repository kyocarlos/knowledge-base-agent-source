"""Infrastructure-free HTTP routes for the v1 API baseline."""

import os

from fastapi import APIRouter, HTTPException, Request

from app.core.config import AppSettings
from app.schemas.common import ApiResponse, HealthData, VersionData


router = APIRouter()


def _response(request: Request, data):
    return ApiResponse(data=data, trace_id=request.state.trace_id)


@router.get("/health", response_model=ApiResponse[HealthData])
async def health(request: Request) -> ApiResponse[HealthData]:
    return _response(request, HealthData(status="ok", live=True, ready=True))


@router.get("/health/live", response_model=ApiResponse[HealthData])
async def live(request: Request) -> ApiResponse[HealthData]:
    return _response(request, HealthData(status="ok", live=True, ready=None))


@router.get("/health/ready", response_model=ApiResponse[HealthData])
async def ready(request: Request) -> ApiResponse[HealthData]:
    if os.getenv("KB_QDRANT_READINESS_REQUIRED", "false").lower() == "true":
        from src.qdrant_readiness import QdrantNotReadyError, check_qdrant_ready

        try:
            check_qdrant_ready()
        except QdrantNotReadyError as exc:
            raise HTTPException(status_code=503, detail={"dependency": "qdrant", "status": "not_ready"}) from exc
    return _response(request, HealthData(status="ok", live=True, ready=True))


@router.get("/version", response_model=ApiResponse[VersionData])
async def version(request: Request) -> ApiResponse[VersionData]:
    settings: AppSettings = request.app.state.settings
    return _response(
        request,
        VersionData(
            service=settings.service_name,
            version=settings.version,
            environment=settings.environment,
            commit=settings.commit,
            release_id=settings.release_id,
            image_digest=settings.image_digest,
            build_timestamp=settings.build_timestamp,
        ),
    )
