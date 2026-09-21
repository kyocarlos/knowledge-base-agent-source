"""Proposed CSIT notification receiver routes (disabled by default)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from ..csit.notification import NotificationError, NotificationReceiver, ReceiverConfig

router = APIRouter(prefix="/api/v1/integrations/csit", tags=["csit-notifications"])
_receiver: NotificationReceiver | None = None


def get_receiver() -> NotificationReceiver:
    global _receiver
    if _receiver is None:
        _receiver = NotificationReceiver(ReceiverConfig.from_env())
    return _receiver


def _error(exc: NotificationError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


@router.post("/events", status_code=202)
async def receive_csit_event(payload: dict, background_tasks: BackgroundTasks,
                             authorization: str | None = Header(default=None)):
    receiver = get_receiver()
    try:
        result = receiver.receive(payload, authorization)
    except NotificationError as exc:
        raise _error(exc) from exc
    # The receipt is committed before this best-effort wake-up.  A later
    # worker/recovery invocation can drain the same durable pending rows.
    background_tasks.add_task(receiver.dispatch_pending)
    return result


@router.get("/events/{event_id}")
async def get_csit_event(event_id: str, authorization: str | None = Header(default=None)):
    try:
        return get_receiver().status(event_id, authorization)
    except NotificationError as exc:
        raise _error(exc) from exc
