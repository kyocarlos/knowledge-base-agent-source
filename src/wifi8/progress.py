"""Progress channel of one WiFi agent task: the worker pushes events, the web process hands them to the asker in order.

Events live in a short-lived Redis list per task (no streaming connection, so no proxy has to be configured for it). The owner is recorded
when the question is submitted; only that owner can read the list. Pieces of streamed text are batched so a long answer is tens of writes, not thousands.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Callable

TTL_SECONDS = int(os.getenv("KM_WIFI8_PROGRESS_TTL_SECONDS", "900"))
MAX_EVENTS = 2000
FLUSH_SECONDS = 0.15


def _events_key(task_id: str) -> str:
    return f"wifi8:agent:events:{task_id}"


def _owner_key(task_id: str) -> str:
    return f"wifi8:agent:owner:{task_id}"


def register(redis: Any, task_id: str, owner: dict[str, Any]) -> None:
    """Called when the question is accepted, before the worker starts."""
    redis.set(_owner_key(task_id), json.dumps(owner, sort_keys=True), ex=TTL_SECONDS)


def read(redis: Any, task_id: str, owner: dict[str, Any], after: int = 0) -> dict[str, Any] | None:
    """Events from position ``after``; None when the task is unknown or belongs to someone else (the caller answers 404 either way)."""
    stored = redis.get(_owner_key(task_id))
    if stored is None:
        return None
    if isinstance(stored, bytes):
        stored = stored.decode("utf-8")
    if json.loads(stored) != json.loads(json.dumps(owner, sort_keys=True)):
        return None
    after = max(0, int(after))
    rows = redis.lrange(_events_key(task_id), after, after + 500 - 1)
    events = [json.loads(r.decode("utf-8") if isinstance(r, bytes) else r) for r in rows]
    return {"events": events, "next": after + len(events), "done": any(e.get("type") == "done" for e in events)}


class Emitter:
    """The ``emit`` callback of run_agent for one task."""

    def __init__(self, redis: Any, task_id: str, clock: Callable[[], float] = time.monotonic) -> None:
        self.redis, self.task_id, self.clock = redis, task_id, clock
        self._pending, self._last, self._count = "", clock(), 0

    def _push(self, event: dict[str, Any]) -> None:
        if self._count >= MAX_EVENTS:
            return
        self._count += 1
        key = _events_key(self.task_id)
        self.redis.rpush(key, json.dumps(event, ensure_ascii=False))
        self.redis.expire(key, TTL_SECONDS)

    def flush(self) -> None:
        if self._pending:
            text, self._pending = self._pending, ""
            self._push({"type": "delta", "text": text})
        self._last = self.clock()

    def __call__(self, event: dict[str, Any]) -> None:
        if event.get("type") == "delta":
            self._pending += str(event.get("text") or "")
            if self.clock() - self._last >= FLUSH_SECONDS:
                self.flush()
            return
        if event.get("type") == "reset":
            self._pending = ""  # text that never reached the reader is dropped; the reader is told to drop what it has
        else:
            self.flush()
        self._push(event)

    def done(self, status: str, **fields: Any) -> None:
        self.flush()
        self._push({"type": "done", "status": status, **fields})
