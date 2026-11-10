"""The island keeper's guide endpoint: a question in, the zones (islands) it belongs to out. It points; it never answers what is inside a zone."""
from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..keeper import routing

router = APIRouter(prefix="/api/keeper", tags=["Island keeper"])

RATE_LIMIT, RATE_WINDOW = 20, 60.0          # questions per account per minute (per worker)
_recent: dict[str, deque] = defaultdict(deque)
MODEL_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_][A-Za-z0-9]+)+|[A-Za-z]{2,}\d[A-Za-z0-9]{2,}")


class RouteBody(BaseModel):
    question: str = Field(min_length=1, max_length=routing.MAX_QUESTION * 2)
    stats: dict | None = None               # {zone id: {week, todo}} as the home page shows them; only used to order the "what is new" pointers


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


def _allow(account: str) -> bool:
    now, queue = time.monotonic(), _recent[account]
    while queue and now - queue[0] > RATE_WINDOW:
        queue.popleft()
    if len(queue) >= RATE_LIMIT:
        return False
    queue.append(now)
    return True


@lru_cache(maxsize=1)
def _zones() -> list[dict]:
    return routing.load_catalogue()


def _llm_complete():
    """One short chat call through the model gateway the other assistants use; None when it is not configured (the keywords then answer)."""
    from .openai_compatible_client import OpenAICompatibleClient
    env = os.environ.get
    model, base_url = env("KM_LLM_PRIMARY_MODEL"), env("KM_LLM_PRIMARY_BASE_URL")
    if not model or not base_url:
        return None
    client = OpenAICompatibleClient(model=model, base_url=base_url, timeout=float(env("KM_KEEPER_LLM_TIMEOUT") or 25), max_tokens=500,
                                    api_key_env=env("KM_LLM_PRIMARY_API_KEY_ENV") or "SUB2API_API_KEY")
    return lambda messages: client.chat(messages, temperature=0.1)


def _entity_zones(question: str) -> list[dict]:
    """Zones whose imported legacy documents mention a model / project name found in the question (needs the legacy import and its graph)."""
    tokens = [t for t in MODEL_TOKEN.findall(question) if len(t) >= 5][:3]
    if not tokens:
        return []
    from .legacy_routes import ZONE_NAMES, _catalogue
    by_name = {name: zone_id for zone_id, name in ZONE_NAMES.items()}
    counts: dict[str, int] = {}
    for token in tokens:
        # a name the documents mention, or part of a document's title (a seminar named "date_host_name" is found by the name, wherever its content put it)
        rows = _catalogue()._run("MATCH (d:LegacyDocument) OPTIONAL MATCH (d)-[:MENTIONS]->(e:LegacyEntity) "
                                 "WITH d, e WHERE toLower(e.name) CONTAINS toLower($t) OR toLower(d.title) CONTAINS toLower($t) "
                                 "RETURN d.topic_zone AS zone, count(DISTINCT d) AS n", t=token)
        for row in rows:
            zone_id = by_name.get(row["zone"])
            if zone_id:
                counts[zone_id] = counts.get(zone_id, 0) + int(row["n"])
    return [{"id": zone_id, "count": n} for zone_id, n in sorted(counts.items(), key=lambda kv: -kv[1])]


@router.post("/route")
async def keeper_route(body: RouteBody, request: Request):
    identity = _identity(request)
    if not _allow(str(identity.get("sub") or "anonymous")):
        raise HTTPException(status_code=429, detail="問得太快了，請稍等一下再問")

    def work():
        try:
            complete = _llm_complete()
        except Exception:  # noqa: BLE001 - not configured: keywords only
            complete = None
        return routing.route(body.question, complete, _zones(), body.stats, entity_zones=_entity_zones)

    return await run_in_threadpool(work)
