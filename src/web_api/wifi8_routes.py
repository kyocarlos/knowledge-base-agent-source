"""Manual upload of Wi-Fi8 export packages into the KM WiFi zone.

Uploading is limited to the accounts listed in ``KM_WIFI8_IMPORT_USERS``
(comma-separated usernames); ``*`` allows every logged-in account of this data
zone. An empty list disables uploads (fail closed).
Reading the import status only requires a KM session for this data zone.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from ..wifi8 import store
from ..wifi8.importer import ImportConflict, Wifi8Importer, Wifi8Settings
from ..wifi8.package import PackageError

router = APIRouter(prefix="/api/wifi8", tags=["Wi-Fi8 import"])
IMPORT_HEADER = "x-km-wifi8-import"
IMPORT_TASK = "tasks.wifi8_import_task"
AGENT_TASK = "tasks.wifi8_agent_task"


def _importer() -> Wifi8Importer:
    return Wifi8Importer(Wifi8Settings.from_environment())


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
        "upload_enabled": bool(_allowed_importers()),
    }


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
