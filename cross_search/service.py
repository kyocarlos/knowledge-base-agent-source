"""Owner-bound, no-cache CrossSearch API and per-zone worker."""
import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import httpx
import redis
from celery import Celery
from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from km_credentials.crypto import CredentialCryptoError, load_private_keys_from_environment, open_envelope

from .connectors import SEARCHERS, SourceAuthError, SourceUnavailable, load_source_config

TTL = 900
ZONE = os.environ["KM_CROSS_SEARCH_ZONE"]
REDIS_URL = os.environ["KM_CROSS_SEARCH_REDIS_URL"]
BRIDGE = os.environ["KM_CROSS_SEARCH_BRIDGE_URL"].rstrip("/")
SECRET = os.environ.get("KM_CROSS_SEARCH_BRIDGE_SECRET", "")
ENABLED = {x.strip() for x in os.getenv("KM_CROSS_SEARCH_SOURCES", "km").split(",") if x.strip()}
EXTERNAL = {"confluence", "jira", "testrail"}
KM_POLL_SECONDS = int(os.getenv("KM_CROSS_SEARCH_KM_POLL_SECONDS", "80"))
SOURCE_TIMEOUT_SECONDS = float(os.getenv("KM_CROSS_SEARCH_SOURCE_TIMEOUT_SECONDS", "5"))
EXTERNAL_BUDGET_SECONDS = float(os.getenv("KM_CROSS_SEARCH_EXTERNAL_BUDGET_SECONDS", "8"))
SOURCE_MAX_CONNECTIONS = int(os.getenv("KM_CROSS_SEARCH_SOURCE_MAX_CONNECTIONS", "4"))
BREAKER_THRESHOLD = int(os.getenv("KM_CROSS_SEARCH_BREAKER_THRESHOLD", "5"))
BREAKER_COOLDOWN_SECONDS = int(os.getenv("KM_CROSS_SEARCH_BREAKER_COOLDOWN_SECONDS", "60"))
ACTIVE_TTL_SECONDS = int(os.getenv("KM_CROSS_SEARCH_ACTIVE_TTL_SECONDS", "180"))
RRF_K = int(os.getenv("KM_CROSS_SEARCH_RRF_K", "60"))
SOURCE_WEIGHTS = {key: float(value) for key, value in json.loads(os.getenv("KM_CROSS_SEARCH_SOURCE_WEIGHTS_JSON", "{}") or "{}").items()}
_PRIVATE_KEYS = None
app = FastAPI(title="KM CrossSearch", version="1")
celery = Celery("km-cross-search", broker=REDIS_URL, backend=REDIS_URL)
r = redis.Redis.from_url(REDIS_URL, decode_responses=True)

_RELEASE_ACTIVE = r.register_script(
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end")


def _active_key(user_id):
    return "cross-search:v1:active:" + ZONE + ":" + user_id


def _release_active(user_id, query_id):
    try:
        _RELEASE_ACTIVE(keys=[_active_key(user_id)], args=[query_id])
    except redis.RedisError:
        pass

class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    sources: list[str] = Field(default_factory=lambda: ["km"], min_length=1, max_length=4)
    topK: int = Field(default=20, ge=1, le=50)
    filters: dict = Field(default_factory=dict)

def _key(query_id):
    return "cross-search:v1:" + ZONE + ":" + query_id

def _bridge(path, payload=None, cookie=None):
    if not SECRET:
        raise HTTPException(503, "cross-search service identity unavailable")
    headers = {"x-km-cross-service": SECRET}
    if cookie:
        headers["cookie"] = "km_entry_session=" + cookie
    with httpx.Client(timeout=10, trust_env=False) as client:
        try:
            response = client.post(BRIDGE + "/api/internal/cross-search/" + path,
                                   headers=headers, json=payload or {})
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(exc.response.status_code, "KM authorization or search failed")
        except httpx.RequestError:
            raise HTTPException(503, "KM data service unavailable")

def _identity(request):
    cookie = request.cookies.get("km_entry_session")
    if not cookie:
        raise HTTPException(401, "KM login required")
    identity = _bridge("identity", cookie=cookie)
    if identity["instance_id"] != ZONE:
        raise HTTPException(403, "wrong KM instance")
    return identity

def _record(query_id):
    raw = r.get(_key(query_id))
    return json.loads(raw) if raw else None

def _store(query_id, value):
    r.setex(_key(query_id), TTL, json.dumps(value, ensure_ascii=False))

def _public(record):
    return {key: record[key] for key in ("queryId", "status", "results", "sourceStatus", "createdAt")}

def _safe_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return None
    parts = urlsplit(value)
    if value.startswith("/") and not value.startswith("//") and not parts.netloc:
        return value
    return None

def _normalize_km(items):
    result = []
    seen = set()
    for rank, item in enumerate(items[:50], 1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("citation_source_name") or item.get("source_name") or item.get("source") or "KM document")[:200]
        content = str(item.get("content") or item.get("snippet") or "")[:500]
        object_id = str(item.get("document_id") or item.get("id") or hashlib.sha256((title + content).encode()).hexdigest())[:160]
        if object_id in seen:
            continue
        seen.add(object_id)
        result.append({"sourceSystem": "km", "objectId": object_id, "title": title,
                       "snippet": content, "url": _safe_url(item.get("url")),
                       "sourceRank": rank, "fusionScore": round(1 / (60 + rank), 8),
                       "citation": {"source": title, "objectId": object_id}})
    return result

@app.get("/health")
def health():
    return {"status": "ok", "zone": ZONE, "sources": sorted(ENABLED)}

@app.get("/api/cross-search/v1/config")
def config(request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    _identity(request)
    return {"enabled": os.getenv("KM_CROSS_SEARCH_UI_ENABLED", "false").lower() == "true",
            "zone": ZONE, "sources": sorted(ENABLED)}

@app.post("/api/cross-search/v1/queries", status_code=202)
def create(payload: Query, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    principal = _identity(request)
    sources = list(dict.fromkeys(payload.sources))
    if any(source not in {"km", *EXTERNAL} for source in sources):
        raise HTTPException(422, "unknown source")
    if any(source not in ENABLED for source in sources):
        raise HTTPException(422, "source not enabled for this KM instance")
    if payload.filters:
        raise HTTPException(422, "filters are not supported by every selected source")
    query_id = str(uuid.uuid4())
    # One running query per KM user per zone, so one person cannot occupy all workers.
    if not r.set(_active_key(principal["user_id"]), query_id, nx=True, ex=ACTIVE_TTL_SECONDS):
        raise HTTPException(429, "a previous query is still running")
    record = {"queryId": query_id, "owner": principal["user_id"], "principal": principal,
              "query": payload.query, "sources": sources, "topK": payload.topK,
              "status": "queued", "results": [],
              "sourceStatus": {source: "queued" for source in sources},
              "createdAt": int(time.time())}
    _store(query_id, record)
    try:
        run_query.delay(query_id)
    except Exception:
        r.delete(_key(query_id))
        _release_active(principal["user_id"], query_id)
        raise HTTPException(503, "search queue unavailable")
    return _public(record)

@app.get("/api/cross-search/v1/queries/{query_id}")
def get(query_id: str, request: Request, response: Response):
    response.headers["Cache-Control"] = "no-store"
    principal = _identity(request)
    try:
        uuid.UUID(query_id)
    except ValueError:
        raise HTTPException(404, "query not found")
    record = _record(query_id)
    if not record or record["owner"] != principal["user_id"] or record["principal"]["instance_id"] != principal["instance_id"]:
        raise HTTPException(404, "query not found")
    return _public(record)

def _run_km(record):
    try:
        launch = _bridge("launch", {**record["principal"], "query": record["query"], "top_k": record["topK"], "filters": {}})
        for _ in range(KM_POLL_SECONDS):
            time.sleep(1)
            reply = _bridge("result", {**record["principal"], "task_id": launch["task_id"]})
            if reply["status"] != "running":
                break
        else:
            reply = {"status": "timeout"}
        if reply["status"] == "completed":
            return "completed", _normalize_km(reply.get("sources", []))[:record["topK"]]
        return reply["status"], []
    except HTTPException as exc:
        return ("rejected" if exc.status_code in (401, 403) else "error"), []
    except Exception:
        return "error", []


def _breaker_key(source):
    return "cross-search:v1:breaker:" + ZONE + ":" + source


def _breaker_open(source):
    try:
        return int(r.get(_breaker_key(source)) or 0) >= BREAKER_THRESHOLD
    except (redis.RedisError, ValueError):
        return False


def _breaker_record(source, ok):
    try:
        if ok:
            r.delete(_breaker_key(source))
        else:
            pipe = r.pipeline()
            pipe.incr(_breaker_key(source))
            pipe.expire(_breaker_key(source), BREAKER_COOLDOWN_SECONDS)
            pipe.execute()
    except redis.RedisError:
        pass


def _private_keys():
    global _PRIVATE_KEYS
    if _PRIVATE_KEYS is None:
        _PRIVATE_KEYS = load_private_keys_from_environment()
    return _PRIVATE_KEYS


def _report_credential(principal, source, ok, code=None):
    try:
        _bridge("credentials/result", {**principal, "source": source, "ok": ok, "error_code": code})
    except HTTPException:
        pass


def _new_client(config):
    """One pooled client per source per task; auth is attached per request, never to the client."""
    return httpx.AsyncClient(verify=config.ca_file or True, trust_env=False,
                             limits=httpx.Limits(max_connections=SOURCE_MAX_CONNECTIONS))


async def _search_external(jobs, query, top_k):
    """jobs: source -> (config, secret). Runs all sources concurrently within the budget."""
    outcomes = {}

    async def one(client, source, config, secret):
        try:
            hits = await SEARCHERS[source](client[source], config, secret, query, top_k, SOURCE_TIMEOUT_SECONDS)
            outcomes[source] = ("completed", hits)
        except SourceAuthError:
            outcomes[source] = ("needs_relink", [])
        except SourceUnavailable as exc:
            outcomes[source] = ("not_configured" if exc.code == "not_configured" else ("timeout" if exc.code == "timeout" else "error"), [])
        except Exception:
            outcomes[source] = ("error", [])

    clients = {source: _new_client(config) for source, (config, _) in jobs.items()}
    try:
        tasks = [asyncio.create_task(one(clients, source, config, secret)) for source, (config, secret) in jobs.items()]
        done, pending = await asyncio.wait(tasks, timeout=EXTERNAL_BUDGET_SECONDS)
        for task in pending:
            task.cancel()
        for source in jobs:
            outcomes.setdefault(source, ("timeout", []))
    finally:
        for client in clients.values():
            await client.aclose()
    return outcomes


def _run_external(record, sources):
    principal = record["principal"]
    statuses, results = {}, []
    try:
        linked = _bridge("credentials", {**principal, "sources": sources})["sources"]
    except HTTPException as exc:
        return {source: ("rejected" if exc.status_code in (401, 403) else "error") for source in sources}, []
    jobs = {}
    for source in sources:
        entry = linked.get(source) or {"status": "not_linked"}
        if entry.get("status") != "active":
            statuses[source] = entry.get("status", "not_linked")
            continue
        try:
            config = load_source_config(source)
        except ValueError:
            config = None
        if config is None:
            statuses[source] = "not_configured"
            continue
        if _breaker_open(source):
            statuses[source] = "unavailable"
            continue
        try:
            # Plaintext exists only in this task's local scope; never stored or logged.
            secret = open_envelope(_private_keys(), entry["envelope"], principal["user_id"], source)
        except CredentialCryptoError:
            statuses[source] = "error"
            continue
        jobs[source] = (config, secret)
    if jobs:
        outcomes = asyncio.run(_search_external(jobs, record["query"], record["topK"]))
        jobs.clear()
        for source, (status, hits) in outcomes.items():
            statuses[source] = status
            results.extend(hits)
            if status == "needs_relink":
                _report_credential(principal, source, False, "source_rejected")
            elif status == "completed":
                _breaker_record(source, True)
                _report_credential(principal, source, True)
            elif status in ("timeout", "error"):
                _breaker_record(source, False)
    return statuses, results


def _fuse(results, top_k):
    """Weighted reciprocal rank fusion over per-source ranks."""
    for item in results:
        item["fusionScore"] = round(SOURCE_WEIGHTS.get(item["sourceSystem"], 1.0) / (RRF_K + item["sourceRank"]), 8)
    return sorted(results, key=lambda item: (-item["fusionScore"], item["sourceSystem"], item["sourceRank"]))[:top_k]


@celery.task(name="cross_search.run_query", soft_time_limit=120, time_limit=150)
def run_query(query_id):
    record = _record(query_id)
    if not record:
        return
    try:
        statuses = {source: "running" for source in record["sources"]}
        record["status"] = "running"
        record["sourceStatus"] = statuses
        _store(query_id, record)
        externals = [source for source in record["sources"] if source in EXTERNAL]
        results = []
        with ThreadPoolExecutor(max_workers=2) as pool:
            km_future = pool.submit(_run_km, record) if "km" in record["sources"] else None
            if externals:
                external_statuses, external_results = _run_external(record, externals)
                statuses.update(external_statuses)
                results.extend(external_results)
            if km_future:
                statuses["km"], km_results = km_future.result()
                results.extend(km_results)
        # Release nothing to a principal whose session or grant changed meanwhile.
        try:
            _bridge("validate", record["principal"])
        except HTTPException:
            results = []
            statuses = {source: "rejected" for source in record["sources"]}
        record["results"] = _fuse(results, record["topK"])
        record["sourceStatus"] = statuses
        record["status"] = "completed" if "completed" in statuses.values() else "failed"
        _store(query_id, record)
    finally:
        _release_active(record["principal"]["user_id"], query_id)
