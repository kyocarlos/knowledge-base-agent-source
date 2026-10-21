"""Infrastructure-free HTTP routes for the v1 API baseline."""

from fastapi import APIRouter, Request

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
    # WP0 has no new infrastructure dependency. Later WPs can add readiness probes here.
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
