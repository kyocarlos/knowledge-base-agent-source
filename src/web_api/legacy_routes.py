"""Legacy (NAS) documents by topic zone: lists, category browsing, search and grounded Q&A. Read-only; the import itself is scripts/import_legacy_docs.py."""
from __future__ import annotations

import os
from functools import lru_cache

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from ..legacy_import import browse

router = APIRouter(prefix="/api/legacy", tags=["Legacy documents"])

# Page zone key -> topic zone name written by the importer. CPE has no zone of its own in the topic table: its documents sit in 4G/5G.
ZONE_NAMES = {
    "csit": "CSIT雜項專區", "wifi": "WiFi 知識專區", "mobile": "4G/5G 知識專區", 
    "equipment": "設備預約知識專區", "cert": "認證與法規知識專區", "lab": "實驗室與測試環境知識專區",
    "broadband": "固網寬頻知識專區", "admin": "部門與公司文管專區",
}


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


def _zone(key: str) -> str:
    if key in ZONE_NAMES:
        return ZONE_NAMES[key]
    if key in ZONE_NAMES.values():
        return key
    raise HTTPException(status_code=404, detail="no such zone")


@lru_cache(maxsize=1)
def _search() -> browse.ZoneSearch:
    from ..report_numeric import vector
    from ..vector_store import VectorStore
    store = VectorStore()
    if not store.available or store.client is None:
        raise HTTPException(status_code=503, detail="向量檢索目前無法使用")
    return browse.ZoneSearch(store.client, store.encode, vector.query_sparse)


@lru_cache(maxsize=1)
def _catalogue() -> browse.ZoneCatalogue:
    from neo4j import GraphDatabase
    uri, user, password = os.getenv("NEO4J_URI"), os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD")
    if not uri:
        raise HTTPException(status_code=503, detail="圖譜資料庫未設定")
    return browse.ZoneCatalogue(GraphDatabase.driver(uri, auth=(user, password)))


def _llm_complete():
    from .openai_compatible_client import OpenAICompatibleClient
    env = os.environ.get
    model, base_url = env("KM_LLM_PRIMARY_MODEL"), env("KM_LLM_PRIMARY_BASE_URL")
    if not model or not base_url:
        raise HTTPException(status_code=503, detail="尚未設定回答用的語言模型")
    client = OpenAICompatibleClient(model=model, base_url=base_url, timeout=float(env("KM_LLM_PRIMARY_TIMEOUT_SECONDS") or 120), max_tokens=2000,
                                    api_key_env=env("KM_LLM_PRIMARY_API_KEY_ENV") or "SUB2API_API_KEY")
    return lambda messages: client.chat(messages, temperature=0.1)


class QueryBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    zone: str
    l1: str | None = Field(default=None, max_length=100)
    l2: str | None = Field(default=None, max_length=100)
    l3: str | None = Field(default=None, max_length=100)
    top_k: int = Field(default=8, ge=1, le=20)


@router.get("/zones")
async def legacy_zones(request: Request):
    _identity(request)
    counts = {row["zone"]: row for row in await run_in_threadpool(lambda: _catalogue().zones())}
    return {"zones": [{"key": key, "name": name, "documents": counts.get(name, {}).get("documents", 0),
                       "needs_review": counts.get(name, {}).get("needs_review", 0)} for key, name in ZONE_NAMES.items()]}


@router.get("/categories")
async def legacy_categories(request: Request, zone: str):
    _identity(request)
    name = _zone(zone)
    return {"zone": name, "categories": await run_in_threadpool(lambda: _catalogue().categories(name))}


@router.get("/documents")
async def legacy_documents(request: Request, zone: str, l1: str | None = None, l2: str | None = None, l3: str | None = None, q: str | None = Query(None, max_length=200),
                           skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
    _identity(request)
    name = _zone(zone)
    return await run_in_threadpool(lambda: _catalogue().documents(name, l1=l1, l2=l2, l3=l3, text=q, skip=skip, limit=limit))


@router.get("/documents/{document_id}")
async def legacy_document(document_id: str, request: Request):
    _identity(request)
    doc = await run_in_threadpool(lambda: _catalogue().document(document_id))
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    chunks = await run_in_threadpool(lambda: _search().document_chunks(document_id))
    return {**doc, "chunks": chunks}


@router.post("/search")
async def legacy_search(body: QueryBody, request: Request):
    _identity(request)
    name = _zone(body.zone)
    hits = await run_in_threadpool(lambda: _search().search(body.query, zone=name, l1=body.l1, l2=body.l2, l3=body.l3, top_k=body.top_k))
    return {"zone": name, "results": hits}


@router.post("/answer")
async def legacy_answer(body: QueryBody, request: Request):
    _identity(request)
    name = _zone(body.zone)

    def work():
        hits = _search().search(body.query, zone=name, l1=body.l1, l2=body.l2, l3=body.l3, top_k=body.top_k)
        return browse.answer(_llm_complete(), body.query, hits)

    return {"zone": name, **await run_in_threadpool(work)}
