"""Protected, disabled-by-default cleanup API for isolated E2E data."""

from __future__ import annotations

import os
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, Request

from ..test_reports.auth import authenticate_e2e_cleanup
from ..test_reports.e2e_cleanup import apply_cleanup, build_cleanup_plan


router = APIRouter(prefix="/api/internal/e2e/v1", tags=["E2E cleanup"])


class CleanupRequest(BaseModel):
    environment: str | None = None
    apply: bool = False


def _enabled() -> bool:
    return os.getenv("KB_E2E_CLEANUP_ENABLED", "false").lower() in {"1", "true", "yes"}


@router.post("/runs/{test_run_id}/cleanup")
async def cleanup_run(test_run_id: str, request: Request, body: CleanupRequest | None = None):
    body = body or CleanupRequest()
    if not _enabled():
        raise HTTPException(status_code=404, detail="E2E cleanup disabled")
    authenticate_e2e_cleanup(request)
    try:
        if body.apply:
            return {"mode": "apply", **apply_cleanup(test_run_id, body.environment)}
        return {"mode": "dry-run", **build_cleanup_plan(test_run_id, body.environment)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="E2E cleanup backend unavailable") from exc
