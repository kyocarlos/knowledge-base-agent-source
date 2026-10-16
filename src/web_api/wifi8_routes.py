"""Manual upload of Wi-Fi8 export packages into the KM WiFi zone.

Uploading is limited to the accounts listed in ``KM_WIFI8_IMPORT_USERS``
(comma-separated usernames); ``*`` allows every logged-in account of this data
zone. An empty list disables uploads (fail closed).
Reading the import status only requires a KM session for this data zone.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from ..wifi8 import store
from ..wifi8.importer import ImportConflict, Wifi8Importer, Wifi8Settings
from ..wifi8.package import PackageError
from ..wifi8.search import SearchOptions, SearchUnavailable, Wifi8Search

router = APIRouter(prefix="/api/wifi8", tags=["Wi-Fi8 import"])
IMPORT_HEADER = "x-km-wifi8-import"
IMPORT_TASK = "tasks.wifi8_import_task"
AGENT_TASK = "tasks.wifi8_agent_task"


def _importer() -> Wifi8Importer:
    return Wifi8Importer(Wifi8Settings.from_environment())


@lru_cache(maxsize=1)
def _vector_store():
    from ..vector_store import VectorStore
    return VectorStore()


def _search_engine(importer: Wifi8Importer | None = None) -> Wifi8Search:
    vector_store = _vector_store()
    if not vector_store.available or vector_store.client is None:
        raise SearchUnavailable("WiFi 向量檢索目前無法使用")
    return Wifi8Search.for_current(
        importer or _importer(),
        qdrant=vector_store.client,
        encoder=vector_store.encode,
        embedding_model=vector_store.model_name,
    )


def _store_path(importer: Wifi8Importer) -> Path:
    path = importer.current_store()
    if not path:
        raise HTTPException(status_code=503, detail="WiFi 專區尚未匯入資料")
    return path


def _documents(importer: Wifi8Importer) -> list[dict[str, Any]]:
    return store.documents(_store_path(importer))


PUBLIC_DOCUMENT_FIELDS = (
    "revision_id", "title", "document_role", "publisher", "document_date",
    "wfa_document_id", "wfa_revision", "version_label", "analysis_eligible",
    "replacement_id", "topics", "supersedes", "segment_count",
    "version_series_id", "document_family_id", "primary_category_id",
)


def _public_document(document: dict[str, Any]) -> dict[str, Any]:
    return {
        key: document.get(key)
        for key in PUBLIC_DOCUMENT_FIELDS
        if document.get(key) not in (None, "", [])
    }


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


def _allowed_importers() -> set[str]:
    return {name.strip() for name in os.getenv("KM_WIFI8_IMPORT_USERS", "").split(",") if name.strip()}


def _importer_username(request: Request) -> str:
    identity = _identity(request)
    allowed = _allowed_importers()
    if not allowed:
        raise HTTPException(status_code=403, detail="Wi-Fi8 package import is not enabled")
    from ..km_control import ControlRegistry
    user = ControlRegistry.from_environment().get_user(identity["sub"])
    if not user or ("*" not in allowed and user.username not in allowed):
        raise HTTPException(status_code=403, detail="This account cannot import Wi-Fi8 packages")
    return user.username


def _can_import(request: Request) -> bool:
    identity = _identity(request)
    allowed = _allowed_importers()
    if not allowed:
        return False
    from ..km_control import ControlRegistry
    user = ControlRegistry.from_environment().get_user(identity["sub"])
    return bool(user and ("*" in allowed or user.username in allowed))


@router.get("/status")
async def wifi8_status(request: Request):
    _identity(request)
    importer = _importer()
    current = importer.current()
    path = importer.current_store()
    return {
        "current": current,
        "counts": store.counts(path) if path else None,
        "source": (store.manifest(path).get("source") if path else None),
        "active_job": importer.active_job(),
        "upload_enabled": _can_import(request),
    }


@router.get("/overview")
async def wifi8_overview(request: Request):
    _identity(request)
    importer = _importer()
    path = _store_path(importer)
    documents = store.documents(path)
    current_documents = [doc for doc in documents if doc.get("analysis_eligible")]
    manifest = store.manifest(path)
    manifest_counts = manifest.get("counts") or {}
    return {
        "current": importer.current(),
        "counts": {
            **store.counts(path),
            "current_documents": len(current_documents),
            "superseded_documents": len(documents) - len(current_documents),
            "excluded": manifest_counts.get("excluded") or {},
        },
        "by_publisher": Counter(
            doc.get("publisher") or "未標示" for doc in current_documents
        ).most_common(),
        "by_document_role": Counter(
            doc.get("document_role") or "未標示" for doc in current_documents
        ).most_common(),
        "top_topics": Counter(
            topic for doc in current_documents for topic in (doc.get("topics") or [])
        ).most_common(20),
        "active_job": importer.active_job(),
        "upload_enabled": _can_import(request),
    }


@router.get("/documents")
async def wifi8_documents(
    request: Request,
    query: str = Query(default="", max_length=200),
    publisher: str = Query(default="", max_length=100),
    document_role: str = Query(default="", max_length=100),
    include_history: bool = False,
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=20, ge=1, le=100),
):
    _identity(request)
    documents = _documents(_importer())
    all_current = [doc for doc in documents if doc.get("analysis_eligible")]
    needle = query.strip().casefold()
    publisher_needle = publisher.strip().casefold()
    role_needle = document_role.strip().casefold()

    def matches(document: dict[str, Any]) -> bool:
        if not include_history and not document.get("analysis_eligible"):
            return False
        if publisher_needle and (document.get("publisher") or "").casefold() != publisher_needle:
            return False
        if role_needle and role_needle not in (document.get("document_role") or "").casefold():
            return False
        if not needle:
            return True
        haystack = " ".join([
            str(document.get("title") or ""),
            str(document.get("revision_id") or ""),
            str(document.get("wfa_document_id") or ""),
            " ".join(str(topic) for topic in (document.get("topics") or [])),
        ]).casefold()
        return needle in haystack

    matched = sorted((doc for doc in documents if matches(doc)), key=lambda doc: (
        str(doc.get("title") or "").casefold(), str(doc.get("revision_id") or "")
    ))
    start = (page - 1) * page_size
    return {
        "total": len(matched),
        "page": page,
        "page_size": page_size,
        "documents": [_public_document(doc) for doc in matched[start:start + page_size]],
        "facets": {
            "publishers": Counter(doc.get("publisher") or "未標示" for doc in all_current).most_common(),
            "document_roles": Counter(doc.get("document_role") or "未標示" for doc in all_current).most_common(),
        },
    }


def _document_or_404(revision_id: str, importer: Wifi8Importer) -> dict[str, Any]:
    if len(revision_id) > 200 or ".." in revision_id:
        raise HTTPException(status_code=404, detail="document not found")
    for document in _documents(importer):
        if document.get("revision_id") == revision_id:
            return document
    raise HTTPException(status_code=404, detail="document not found")


@router.get("/documents/{revision_id}")
async def wifi8_document(revision_id: str, request: Request):
    _identity(request)
    importer = _importer()
    document = _document_or_404(revision_id, importer)
    series = document.get("version_series_id") or document.get("document_family_id")
    all_documents = _documents(importer)
    versions = [doc for doc in all_documents if series and (
        doc.get("version_series_id") == series or doc.get("document_family_id") == series
    )]
    related_ids = set(document.get("supersedes") or []) | {revision_id}
    versions.extend(doc for doc in all_documents if (
        doc.get("revision_id") in related_ids
        or revision_id in (doc.get("supersedes") or [])
        or doc.get("replacement_id") == revision_id
        or document.get("replacement_id") == doc.get("revision_id")
    ))
    deduplicated = {doc["revision_id"]: doc for doc in versions if doc.get("revision_id")}
    return {
        "document": _public_document(document),
        "versions": [
            _public_document(doc) for doc in sorted(
                deduplicated.values(),
                key=lambda doc: (str(doc.get("document_date") or ""), str(doc.get("wfa_revision") or "")),
            )
        ],
    }


@router.get("/documents/{revision_id}/chunks")
async def wifi8_document_chunks(
    revision_id: str,
    request: Request,
    start: int = Query(default=1, ge=1, le=1000000),
    count: int = Query(default=8, ge=1, le=20),
):
    _identity(request)
    importer = _importer()
    _document_or_404(revision_id, importer)
    with store.connect(_store_path(importer), readonly=True) as database:
        total = database.execute(
            "SELECT count(*) FROM chunks WHERE revision_id = ?", (revision_id,)
        ).fetchone()[0]
        rows = database.execute(
            "SELECT ordinal, location, location_label, text FROM chunks "
            "WHERE revision_id = ? AND ordinal >= ? ORDER BY ordinal LIMIT ?",
            (revision_id, start, count),
        ).fetchall()
    chunks = [{
        "chunk_index": row["ordinal"],
        "location": json.loads(row["location"]),
        "location_label": row["location_label"],
        "content": row["text"],
    } for row in rows]
    return {
        "revision_id": revision_id,
        "total": total,
        "start": start,
        "count": len(chunks),
        "next_start": start + len(chunks) if start + len(chunks) <= total else None,
        "chunks": chunks,
    }


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=10, ge=1, le=20)
    include_history: bool = False
    publishers: list[str] = Field(default_factory=list, max_length=10)
    document_roles: list[str] = Field(default_factory=list, max_length=10)


@router.post("/search")
async def wifi8_search(body: SearchRequest, request: Request):
    _identity(request)
    try:
        engine = _search_engine()
        return engine.search(body.query.strip(), SearchOptions(
            top_k=body.top_k,
            include_history=body.include_history,
            publishers=tuple(value.strip()[:100] for value in body.publishers if value.strip()),
            document_roles=tuple(value.strip()[:100] for value in body.document_roles if value.strip()),
        ))
    except SearchUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/jobs")
async def wifi8_jobs(request: Request, limit: int = Query(default=20, ge=1, le=100)):
    _identity(request)
    importer = _importer()
    jobs = []
    for path in (importer.root / "jobs").glob("wifi8-import-*.json"):
        job = importer.job(path.stem)
        if job:
            jobs.append(job)
    jobs.sort(key=lambda job: str(job.get("updated_at") or job.get("created_at") or ""), reverse=True)
    return {"jobs": jobs[:limit], "active_job": importer.active_job()}


@router.get("/jobs/{job_id}")
async def wifi8_job(job_id: str, request: Request):
    _identity(request)
    if not job_id.startswith("wifi8-import-") or "/" in job_id or ".." in job_id:
        raise HTTPException(status_code=404, detail="job not found")
    job = _importer().job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.post("/packages", status_code=202)
async def upload_wifi8_package(request: Request, file: UploadFile):
    if request.headers.get(IMPORT_HEADER) != "1":
        raise HTTPException(status_code=403, detail="Same-origin Wi-Fi8 import request required")
    username = _importer_username(request)
    importer = _importer()
    limit = importer.settings.max_package_bytes
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(status_code=422, detail="請上傳 Wi-Fi8 匯出的 .zip 檔")
    tmp_root = importer.root / "tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=tmp_root, suffix=".zip", delete=False) as handle:
        temp = Path(handle.name)
        size = 0
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                handle.close()
                temp.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="匯出包超過大小上限")
            handle.write(chunk)
    try:
        job = importer.submit(temp, submitted_by=username)
    except ImportConflict as exc:
        raise HTTPException(status_code=409, detail="已有匯入工作進行中，請等待完成") from exc
    except PackageError as exc:
        raise HTTPException(status_code=422, detail=f"匯出包驗證失敗：{exc}") from exc
    finally:
        temp.unlink(missing_ok=True)
    if job["status"] == "queued":
        _enqueue(job["job_id"])
    return job


def _enqueue(job_id: str) -> None:
    # By task name: the web image's tasks module may predate the worker's.
    from .tasks import celery_app
    celery_app.send_task(IMPORT_TASK, args=[job_id], queue="ingest")


class AgentTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class AgentRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[AgentTurn] = Field(default_factory=list, max_length=12)


def _owner(identity: dict) -> dict:
    return {"user_id": identity["sub"], "instance_id": identity.get("instance_id")}


@router.post("/agent", status_code=202)
async def ask_wifi8_agent(body: AgentRequest, request: Request):
    owner = _owner(_identity(request))
    from .tasks import celery_app
    task = celery_app.send_task(AGENT_TASK, args=[body.question.strip(), [t.model_dump() for t in body.history], owner],
                                queue="search")
    return {"task_id": task.id, "status": "submitted"}


@router.get("/agent/{task_id}")
async def wifi8_agent_result(task_id: str, request: Request):
    owner = _owner(_identity(request))
    from celery.result import AsyncResult
    from .tasks import celery_app
    result = AsyncResult(task_id, app=celery_app)
    if not result.ready():
        return {"task_id": task_id, "status": "pending"}
    value = result.result if isinstance(result.result, dict) else None
    # Results belong to the asker; another user's task id reveals nothing.
    if not value or value.get("owner") != owner:
        raise HTTPException(status_code=404, detail="task not found")
    return {"task_id": task_id, **{k: v for k, v in value.items() if k != "owner"}}
