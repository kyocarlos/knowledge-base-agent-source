"""Private, owner-bound source-only KM search bridge."""
import hmac
import json
import os
import uuid

import redis
from celery.result import AsyncResult
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..instance_isolation import configured_instance_id
from ..km_control import ControlRegistry, verify_entry_session, ControlError
from .tasks import search_task

router = APIRouter(prefix="/api/internal/cross-search", tags=["internal cross search"])
TTL = 900

class Principal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: str
    instance_id: str
    role: str
    epoch: int

class Launch(Principal):
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=20, ge=1, le=50)
    filters: dict = Field(default_factory=dict)

class Lookup(Principal):
    task_id: str

class CredentialRequest(Principal):
    sources: list[str] = Field(min_length=1, max_length=3)

class CredentialResult(Principal):
    source: str
    ok: bool
    error_code: str | None = Field(default=None, max_length=64)

def _service(secret: str | None) -> None:
    expected = os.getenv("KM_CROSS_SEARCH_BRIDGE_SECRET", "")
    if not expected:
        raise HTTPException(503, "cross-search bridge disabled")
    if not secret or not hmac.compare_digest(secret, expected):
        raise HTTPException(401, "service identity required")

def _validate(principal: Principal) -> None:
    if principal.instance_id != configured_instance_id():
        raise HTTPException(403, "wrong KM instance")
    try:
        ControlRegistry.from_environment().validate_entry_claims(
            principal.user_id, principal.instance_id, principal.role, principal.epoch
        )
    except ControlError:
        raise HTTPException(403, "KM grant revoked")

def _registry():
    url = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL")
    if not url:
        raise HTTPException(503, "bridge registry unavailable")
    return redis.Redis.from_url(url, decode_responses=True)

@router.post("/identity")
def identity(request: Request, x_km_cross_service: str | None = Header(default=None)):
    _service(x_km_cross_service)
    try:
        claims = verify_entry_session(request.cookies.get("km_entry_session", ""), configured_instance_id())
        result = Principal(user_id=claims["sub"], instance_id=claims["instance_id"], role=claims["role"], epoch=claims["epoch"])
        _validate(result)
        return result
    except ControlError:
        raise HTTPException(401, "KM login required")

@router.post("/validate")
def validate(payload: Principal, x_km_cross_service: str | None = Header(default=None)):
    """Re-check the grant/session epoch before results are released."""
    _service(x_km_cross_service)
    _validate(payload)
    return {"status": "valid"}

@router.post("/credentials")
def credentials(payload: CredentialRequest, x_km_cross_service: str | None = Header(default=None)):
    """Sealed envelopes of the validated principal only; never plaintext."""
    _service(x_km_cross_service)
    _validate(payload)
    try:
        return {"sources": ControlRegistry.from_environment().source_credential_envelopes(payload.user_id, payload.sources)}
    except ControlError:
        raise HTTPException(503, "source credential store unavailable")

@router.post("/credentials/result")
def credential_result(payload: CredentialResult, x_km_cross_service: str | None = Header(default=None)):
    _service(x_km_cross_service)
    _validate(payload)
    try:
        ControlRegistry.from_environment().mark_source_credential_result(payload.user_id, payload.source, payload.ok, payload.error_code)
    except ControlError:
        raise HTTPException(503, "source credential store unavailable")
    return {"status": "recorded"}

@router.post("/launch")
def launch(payload: Launch, x_km_cross_service: str | None = Header(default=None)):
    _service(x_km_cross_service)
    _validate(payload)
    if payload.filters:
        raise HTTPException(422, "filters are not enabled for KM bridge")
    task = search_task.apply_async(args=[payload.query, "vector"], kwargs={
        "user_id": payload.user_id, "top_k": payload.top_k,
        "sources_only": True, "filters": {},
    })
    key = "cross-bridge:" + task.id
    _registry().setex(key, TTL, json.dumps(payload.model_dump(include={"user_id", "instance_id", "role", "epoch"})))
    return {"task_id": task.id, "status": "submitted"}

@router.post("/result")
def result(payload: Lookup, x_km_cross_service: str | None = Header(default=None)):
    _service(x_km_cross_service)
    _validate(payload)
    try:
        uuid.UUID(payload.task_id)
    except ValueError:
        raise HTTPException(404, "task not found")
    record = _registry().get("cross-bridge:" + payload.task_id)
    if not record or json.loads(record) != payload.model_dump(include={"user_id", "instance_id", "role", "epoch"}):
        raise HTTPException(404, "task not found")
    task = AsyncResult(payload.task_id, app=search_task.app)
    if not task.ready():
        return {"status": "running"}
    if task.failed():
        return {"status": "failed", "error": "KM search failed"}
    value = task.result
    if not isinstance(value, dict) or value.get("status") != "completed":
        return {"status": "failed", "error": "KM search failed"}
    return {"status": "completed", "sources": value.get("sources", [])[:50]}
