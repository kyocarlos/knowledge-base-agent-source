"""HTTP side of the answer export: ask what the user wants, show the outline, then write the file.

Every route needs a KM login and the ``wifi8_user_files`` capability (config/km_capabilities.json, one switch for attaching files and
exporting answers). The capability is looked up in KM Control on every call, so revoking it applies at once; any failure means no.
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import builders
from .planner import MAX_ANSWERS, PlanError, plan
from .spec import FORMATS, ExportSpec
from .store import ExportSettings, ExportStore, RateLimiter

logger = logging.getLogger(__name__)
CAPABILITY = "wifi8_user_files"  # config/km_capabilities.json: attaching files and exporting answers share this switch
REQUEST_HEADER = "x-km-export"
router = APIRouter(prefix="/api/export", tags=["Answer export"])
_limiter = RateLimiter()


MAX_MULTI_CHARS = 40000  # all selected answers together


class PlanItem(BaseModel):
    question: str = Field(default="", max_length=2000)
    answer: str = Field(min_length=1, max_length=20000)
    sources: list[str] = Field(default_factory=list, max_length=30)


class PlanRequest(BaseModel):
    """One answer (``answer``) or several (``items``, at most MAX_ANSWERS, checked in the route so the message can be specific)."""
    question: str = Field(default="", max_length=2000)
    answer: str = Field(default="", max_length=20000)
    sources: list[str] = Field(default_factory=list, max_length=30)
    items: list[PlanItem] = Field(default_factory=list, max_length=50)
    request: str = Field(default="", max_length=1000)
    format: str | None = Field(default=None, max_length=8)


class BuildRequest(BaseModel):
    spec: ExportSpec


@lru_cache(maxsize=1)
def _store() -> ExportStore:
    return ExportStore(ExportSettings.from_environment())


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


def _may_export(request: Request) -> bool:
    identity = _identity(request)
    try:
        from ..km_control import ControlRegistry
        return ControlRegistry.from_environment().has_capability(str(identity.get("sub")), str(identity.get("instance_id")), CAPABILITY)
    except Exception:  # noqa: BLE001 - fail closed
        logger.warning("export capability lookup failed", exc_info=True)
        return False


def _require(request: Request, *, write: bool = False) -> str:
    owner = f"{_identity(request).get('instance_id')}:{_identity(request).get('sub')}"
    if not _may_export(request):
        raise HTTPException(status_code=403, detail="This account is not authorised to export answers")
    if write and request.headers.get(REQUEST_HEADER) != "1":
        raise HTTPException(status_code=403, detail="Same-origin export request required")
    return owner


def _llm_complete():
    """One chat call through the same OpenAI-compatible gateway the assistants use."""
    from ..web_api.openai_compatible_client import OpenAICompatibleClient
    env = os.environ.get  # the same gateway settings the web service uses; KM_EXPORT_LLM_* only overrides them
    model = env("KM_EXPORT_LLM_MODEL") or env("KM_LLM_PRIMARY_MODEL")
    base_url = env("KM_EXPORT_LLM_BASE_URL") or env("KM_LLM_PRIMARY_BASE_URL")
    if not model or not base_url:
        raise RuntimeError("no LLM model / base URL configured for the export service")
    client = OpenAICompatibleClient(model=model, base_url=base_url, timeout=float(env("KM_EXPORT_LLM_TIMEOUT") or env("KM_LLM_PRIMARY_TIMEOUT_SECONDS") or 120),
                                    max_tokens=6000, api_key_env=env("KM_LLM_PRIMARY_API_KEY_ENV") or "SUB2API_API_KEY")
    return lambda messages: client.chat(messages, temperature=0.2)


@router.get("/config")
async def export_config(request: Request):
    """Whether this account may export, and what the page shows. Any logged-in account may ask."""
    _identity(request)
    allowed = _may_export(request)
    settings = ExportSettings.from_environment()
    return {"enabled": allowed, **({"formats": list(FORMATS), "max_answers": MAX_ANSWERS, **settings.public()} if allowed else {})}


@router.post("/plan")
async def export_plan(body: PlanRequest, request: Request):
    """Ask the model for an outline of the file. Nothing is written yet: the user reads it and decides."""
    owner = _require(request, write=True)
    if body.format is not None and body.format not in FORMATS:
        raise HTTPException(status_code=422, detail="unsupported format")
    multi = bool(body.items)
    if multi:
        if len(body.items) > MAX_ANSWERS:
            raise HTTPException(status_code=422, detail=f"一次最多匯出 {MAX_ANSWERS} 則回答，請取消幾則再試")
        if sum(len(i.answer) for i in body.items) > MAX_MULTI_CHARS:
            raise HTTPException(status_code=413, detail="所選回答的內容太長，請減少所選的回答再試")
    elif not body.answer.strip():
        raise HTTPException(status_code=422, detail="沒有可匯出的回答內容")
    settings = ExportSettings.from_environment()
    if not _limiter.allow(f"{'multi' if multi else 'plan'}:{owner}", settings.multi_plans_per_hour if multi else settings.plans_per_hour):
        raise HTTPException(status_code=429, detail="匯出次數已達每小時上限，請稍後再試")
    try:
        spec = await run_in_threadpool(lambda: plan(_llm_complete(), question=body.question, answer=body.answer, sources=body.sources, request=body.request, fmt=body.format,
                                                    items=body.items if multi else None))
    except PlanError as exc:
        if str(exc) == "llm_unavailable":
            raise HTTPException(status_code=503, detail="語言模型暫時無法使用，請稍後再試") from exc
        raise HTTPException(status_code=502, detail="無法整理出可用的內容，請換個說法或稍後再試") from exc
    except RuntimeError as exc:  # settings missing
        logger.error("export plan: %s", exc)
        raise HTTPException(status_code=503, detail="匯出服務尚未設定語言模型") from exc
    return {"spec": spec.model_dump(), "outline": spec.outline()}


@router.post("/build", status_code=201)
async def export_build(body: BuildRequest, request: Request):
    """Write the file from the spec the user confirmed (no model call)."""
    owner = _require(request, write=True)
    if not _limiter.allow(f"build:{owner}", ExportSettings.from_environment().builds_per_hour):
        raise HTTPException(status_code=429, detail="匯出次數已達每小時上限，請稍後再試")
    try:
        data, media_type, name = await run_in_threadpool(builders.build, body.spec)
        return _store().save(owner, data, media_type, name)
    except ValueError as exc:
        raise HTTPException(status_code=413, detail="檔案太大，請減少內容") from exc
    except Exception as exc:  # noqa: BLE001 - nothing about the content goes to the log
        logger.warning("export build failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="檔案產生失敗，請稍後再試") from exc


@router.get("/files/{file_id}")
async def export_download(file_id: str, request: Request):
    owner = _require(request)
    found = _store().open(owner, file_id)
    if not found:
        raise HTTPException(status_code=404, detail="file not found or expired")
    path, meta = found
    return FileResponse(path, media_type=meta["media_type"], headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(meta['name'])}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",  # a downloaded .html must never run in the KM origin
        "Cache-Control": "private, no-store",
    })


def create_app() -> FastAPI:
    app = FastAPI(title="KM answer export", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(router)
    from ..web_api.instance_auth_routes import InstanceAuthMiddleware  # same login check as the other KM services
    app.add_middleware(InstanceAuthMiddleware)
    return app
