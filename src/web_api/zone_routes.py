"""Knowledge zone pages (all zones except WiFi) on real data: the documents CSIT delivered, grouped by the zone KM decided for them.

The pages were written against the WiFi zone's /api/wifi8/* contract; these routes answer the same calls under /api/zones/{zone}/ from the
vector collections (see zone_pages/). Attached files, feedback and progress events reuse the WiFi zone's own helpers.
"""
from __future__ import annotations

import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..csit_integration_v1.zones import PAGE_KEY, UNCLASSIFIED, ZONE_BY_ID, search_names
from ..wifi8 import feedback, progress, userfiles
from ..zone_pages import views
from ..zone_pages.agent import TaskStore, ZoneAgent
from ..zone_pages.catalog import ZoneCatalog
from ..zone_pages.digest import DigestService

logger = logging.getLogger("km.zones")
router = APIRouter(prefix="/api/zones/{zone}", tags=["Knowledge zones"])
PAGES = {PAGE_KEY.get(z, z): z for z in ZONE_BY_ID if z != "wifi"}      # page id -> zone id (the page "csit" is 產品驗證專區)
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="zone-agent")


def _zone(zone: str) -> tuple[str, str, list[str]]:
    """(zone id, label, topic_zone values). 產品驗證專區 also lists what KM could not place yet, next to its own documents."""
    zone_id = PAGES.get(zone)
    if zone_id is None:
        raise HTTPException(status_code=404, detail="no such zone")
    names = search_names(zone_id)
    return zone_id, ZONE_BY_ID[zone_id], names + ([UNCLASSIFIED[1]] if zone_id == "verification" else [])


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


def _owner(identity: dict) -> dict:
    return {"user_id": identity["sub"], "instance_id": identity.get("instance_id")}


@lru_cache(maxsize=1)
def _catalog() -> ZoneCatalog:
    from ..vector_store import VectorStore
    store = VectorStore()
    if not store.available or store.client is None:
        raise HTTPException(status_code=503, detail="向量檢索目前無法使用")
    return ZoneCatalog(store.client, store.encode)


def _redis():
    from . import tasks
    return tasks.get_redis_client()


def _complete():
    """The model that writes answers and digest highlights; None when no model is configured."""
    from .legacy_routes import _llm_complete
    try:
        return _llm_complete()
    except HTTPException:
        return None


@lru_cache(maxsize=1)
def _digest() -> DigestService:
    return DigestService(_complete(), _redis())


@router.get("/overview")
async def zone_overview(zone: str, request: Request):
    _identity(request)
    _, label, names = _zone(zone)
    docs = await run_in_threadpool(lambda: _catalog().documents(names))
    return views.overview(docs, label)


@router.get("/documents")
async def zone_documents(zone: str, request: Request, query: str = "", publisher: str | None = None, document_role: str | None = None, include_history: str = "",
                         page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    _identity(request)
    _, _, names = _zone(zone)
    docs = await run_in_threadpool(lambda: _catalog().documents(names))
    return views.list_documents(docs, query=query, publisher=publisher, role=document_role, history=include_history in ("on", "true", "1"), page=page, size=page_size)


def _doc(zone_names: list[str], revision_id: str) -> dict:
    doc = _catalog().document(zone_names, revision_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    return doc


@router.get("/documents/{revision_id:path}/chunks")
async def zone_document_chunks(zone: str, revision_id: str, request: Request, count: int = Query(8, ge=1, le=200), figures: str = ""):
    _identity(request)
    _, _, names = _zone(zone)
    if figures in ("true", "1"):
        return {"chunks": [], "total": 0}                       # no figures are extracted from CSIT documents
    doc = await run_in_threadpool(lambda: _doc(names, revision_id))
    rows, total = await run_in_threadpool(lambda: _catalog().chunks(doc, count))
    return {"chunks": rows, "total": total}


@router.get("/documents/{revision_id:path}")
async def zone_document(zone: str, revision_id: str, request: Request):
    _identity(request)
    _, _, names = _zone(zone)
    doc = await run_in_threadpool(lambda: _doc(names, revision_id))
    return {"document": views.doc_view(doc), "versions": [views.doc_view(d) for d in _catalog().versions(names, doc)]}


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=30)
    include_history: bool = False


@router.post("/search")
async def zone_search(zone: str, body: SearchBody, request: Request):
    _identity(request)
    _, _, names = _zone(zone)
    hits = await run_in_threadpool(lambda: _catalog().search(body.query.strip(), names, body.top_k, body.include_history))
    return {"policy": "向量檢索（專區內）", "results": [views.search_result(h) for h in hits]}


@router.get("/feed")
async def zone_feed(zone: str, request: Request):
    _identity(request)
    _, label, names = _zone(zone)

    def work():
        docs = _catalog().documents(names)
        return views.feed(docs, _digest().build(label, docs))

    return await run_in_threadpool(work)


# ---------- questions ----------
class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)
    sources: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=5)


class AgentBody(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[Turn] = Field(default_factory=list, max_length=60)
    file_ids: list[str] = Field(default_factory=list, max_length=5)


def _run(task_id: str, zone_label: str, names: list[str], body: AgentBody, owner: dict, records: dict) -> None:
    redis = _redis()
    emit = progress.Emitter(redis, task_id)
    store = TaskStore(redis)
    try:
        result = ZoneAgent(_catalog(), _complete()).answer(task_id=task_id, zone_label=zone_label, zone_names=names, question=body.question.strip(),
                                                           history=[t.model_dump() for t in body.history], owner=owner, file_records=records, emit=emit)
        store.save(task_id, result)
        emit.done("completed")
    except Exception as exc:  # noqa: BLE001 - the page shows the failure instead of waiting for ever
        logger.warning("zone answer failed: %s", type(exc).__name__, exc_info=True)
        store.save(task_id, {"task_id": task_id, "owner": owner, "status": "failed", "question": body.question, "error": "回答暫時無法產生，請稍後再試"})
        emit.done("failed")


@router.post("/agent", status_code=202)
async def zone_ask(zone: str, body: AgentBody, request: Request):
    owner = _owner(_identity(request))
    _, label, names = _zone(zone)
    file_ids = list(dict.fromkeys(body.file_ids))
    if not all(userfiles.FILE_ID.match(i) for i in file_ids):
        raise HTTPException(status_code=422, detail="invalid file id")
    records = {}
    if file_ids:
        from .wifi8_routes import _user_file_store
        store = _user_file_store()
        records = {i: r for i in file_ids if (r := store.get(owner, i))}
    task_id = str(uuid.uuid4())
    progress.register(_redis(), task_id, owner)
    _pool.submit(_run, task_id, label, names, body, owner, records)
    return {"task_id": task_id, "status": "submitted", "stream": True, "feedback": _feedback_enabled()}


@router.get("/agent/{task_id}/events")
async def zone_events(zone: str, task_id: str, request: Request, after: int = 0):
    owner = _owner(_identity(request))
    _zone(zone)
    value = progress.read(_redis(), task_id, owner, after)
    if value is None:
        raise HTTPException(status_code=404, detail="task not found")
    return value


@router.get("/agent/{task_id}")
async def zone_result(zone: str, task_id: str, request: Request):
    owner = _owner(_identity(request))
    _zone(zone)
    redis = _redis()
    if redis.get(progress._owner_key(task_id)) is None and TaskStore(redis).get(task_id) is None:
        raise HTTPException(status_code=404, detail="task not found")
    value = TaskStore(redis).get(task_id)
    if value is None:
        return {"task_id": task_id, "status": "pending"}
    if value.get("owner") != owner:
        raise HTTPException(status_code=404, detail="task not found")
    return {k: v for k, v in value.items() if k != "owner"}


# ---------- feedback ----------
def _feedback_enabled() -> bool:
    import os
    return os.getenv("KM_WIFI8_FEEDBACK", "0").strip().lower() in {"1", "true", "yes", "on"}


class FeedbackBody(BaseModel):
    rating: str = Field(pattern="^(up|down)$")
    reasons: list[str] = Field(default_factory=list, max_length=6)
    comment: str = Field(default="", max_length=500)


@router.get("/agent-feedback/options")
async def zone_feedback_options(zone: str, request: Request):
    _identity(request)
    if not _feedback_enabled():
        raise HTTPException(status_code=404, detail="feedback is not enabled")
    return {"reasons": [{"key": k, "label": v} for k, v in feedback.REASONS.items()]}


@router.post("/agent/{task_id}/feedback")
async def zone_feedback(zone: str, task_id: str, body: FeedbackBody, request: Request):
    owner = _owner(_identity(request))
    _zone(zone)
    if not _feedback_enabled():
        raise HTTPException(status_code=404, detail="feedback is not enabled")
    value = TaskStore(_redis()).get(task_id)
    if not value or value.get("owner") != owner or value.get("status") != "completed":
        raise HTTPException(status_code=404, detail="task not found")
    from .wifi8_routes import _wifi8_root
    try:
        return feedback.save(_wifi8_root() / "zones" / zone, task_id, owner, body.rating, body.reasons, body.comment, value)
    except feedback.FeedbackError as exc:
        raise HTTPException(status_code=422, detail=f"invalid {exc}") from exc
    except OSError as exc:
        raise HTTPException(status_code=503, detail="feedback could not be saved") from exc


# ---------- attached files (the WiFi zone's own store and rules; a file lives for one conversation and is not added to any zone) ----------
@router.get("/files/config")
async def zone_files_config(zone: str, request: Request):
    _identity(request)
    return {"enabled": True, **userfiles.UserFileSettings.from_environment().public()}


@router.get("/files")
async def zone_files(zone: str, request: Request):
    owner = _owner(_identity(request))
    from .wifi8_routes import _user_file_store
    return {"files": _user_file_store().list(owner)}


@router.post("/files", status_code=201)
async def zone_upload(zone: str, request: Request, file: UploadFile):
    from . import wifi8_routes as w
    if request.headers.get(w.USERFILE_HEADER) != "1":
        raise HTTPException(status_code=403, detail="Same-origin file request required")
    owner = _owner(_identity(request))
    settings = userfiles.UserFileSettings.from_environment()
    data = bytearray()
    while chunk := await file.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > settings.max_bytes:
            raise HTTPException(status_code=413, detail=f"檔案超過 {settings.max_bytes // (1024 * 1024)} MB 上限")
    try:
        store = w._user_file_store()
        if len(store.ids(owner)) >= settings.max_files:
            raise userfiles.UserFileError(f"最多同時附加 {settings.max_files} 個檔案，請先移除一個", 409)
        async with w._parse_slots:
            record = await run_in_threadpool(userfiles.build_record, file.filename or "file", bytes(data), settings, w._image_describer())
        file_id = store.save(owner, record)
    except userfiles.UserFileError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("zone user file not stored: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="檔案暫時無法處理，請稍後再試") from exc
    return {**userfiles.UserFileStore.summary(file_id, record), "expires_in": settings.ttl_seconds}


@router.delete("/files/{file_id}")
async def zone_delete_file(zone: str, file_id: str, request: Request):
    from . import wifi8_routes as w
    if request.headers.get(w.USERFILE_HEADER) != "1":
        raise HTTPException(status_code=403, detail="Same-origin file request required")
    owner = _owner(_identity(request))
    if not w._user_file_store().delete(owner, file_id):
        raise HTTPException(status_code=404, detail="file not found")
    return {"deleted": file_id}
