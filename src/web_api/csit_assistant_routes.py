"""CSIT zone AI assistants for the browser (KM entry session required, like the Wi-Fi8 zone)."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..csit import assistants

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/csit-assistants", tags=["CSIT assistants"])


class AssistantQuery(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


def _public(assistant: dict, state: dict) -> dict:
    return {"id": assistant["id"], "name": assistant.get("name", assistant["id"]), "purpose": assistant.get("purpose", ""),
            "examples": assistant.get("examples", []), "status": state["status"],
            "requirements": [{"id": r["id"], "label": r["label"], "ok": r["ok"], "reason": r["reason"]} for r in state["requirements"]]}


@router.get("")
async def list_assistants(request: Request):
    _identity(request)
    items = assistants.load_registry()
    states = [await run_in_threadpool(assistants.readiness, item) for item in items]
    return {"assistants": [_public(item, state) for item, state in zip(items, states)]}


@router.post("/{assistant_id}/query")
async def query_assistant(assistant_id: str, body: AssistantQuery, request: Request):
    identity = _identity(request)
    assistant = assistants.get_assistant(assistant_id)
    if assistant is None:
        raise HTTPException(status_code=404, detail="Unknown CSIT assistant")
    result = await run_in_threadpool(assistants.answer, assistant, body.question)
    logger.info("csit assistant query assistant=%s status=%s user=%s", assistant_id, result["status"], identity.get("sub"))
    return {"assistant_id": assistant_id, **result}
