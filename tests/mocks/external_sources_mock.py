"""Mock Confluence / Jira / TestRail for CrossSearch tests (no real systems).

Each mock user sees only their own documents, so per-user credential use is
observable: a result leaking between users means credentials were mixed up.
Every request records which user authenticated it.  Latency is configurable
with `MOCK_LATENCY_SECONDS` (also per source, e.g. `MOCK_JIRA_LATENCY_SECONDS`).
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
from urllib.parse import parse_qs

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_NAMES = [name.strip() for name in os.getenv("MOCK_USERS", "alice,bob,carol,dave,erin").split(",") if name.strip()]
USERS = {name: {"password": f"{name}-pass", "token": f"{name}-pat"} for name in _NAMES}
DOCS = {name: [f"Throughput n78 {name} report", f"WiFi 6 throughput {name} plan"] for name in _NAMES}
REQUESTS: list[dict] = []
app = FastAPI(title="mock external sources")


def _user(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.startswith("Basic "):
        try:
            username, _, password = base64.b64decode(header[6:]).decode().partition(":")
        except ValueError:
            return None
        return username if USERS.get(username, {}).get("password") == password else None
    if header.startswith("Bearer "):
        token = header[7:]
        return next((name for name, item in USERS.items() if item["token"] == token), None)
    return None


async def _latency(source: str) -> None:
    delay = float(os.getenv(f"MOCK_{source.upper()}_LATENCY_SECONDS", os.getenv("MOCK_LATENCY_SECONDS", "0")))
    if delay:
        await asyncio.sleep(delay)


def _matches(user: str, text: str) -> list[tuple[int, str]]:
    words = [word.lower() for word in re.findall(r"\w+", text)]
    return [(index, title) for index, title in enumerate(DOCS.get(user, []), 1) if words and all(word in title.lower() for word in words)]


def _quoted(value: str) -> str:
    match = re.search(r'~ "([^"]*)"', value)
    return match.group(1) if match else ""


def _record(source: str, user: str | None, query: str) -> None:
    REQUESTS.append({"source": source, "user": user, "query": query})


@app.get("/confluence/rest/api/content/search")
async def confluence(request: Request, cql: str, limit: int = 20):
    user = _user(request)
    _record("confluence", user, cql)
    await _latency("confluence")
    if not user:
        return JSONResponse({"message": "unauthorized"}, status_code=401)
    hits = _matches(user, _quoted(cql))[:limit]
    return {"results": [{"id": f"{user}-{index}", "title": title, "space": {"key": "DA40"}} for index, title in hits]}


@app.get("/jira/rest/api/2/search")
async def jira(request: Request, jql: str, maxResults: int = 20):
    user = _user(request)
    _record("jira", user, jql)
    await _latency("jira")
    if not user:
        return JSONResponse({"errorMessages": ["unauthorized"]}, status_code=401)
    hits = _matches(user, _quoted(jql))[:maxResults]
    return {"issues": [{"key": f"{user.upper()}-{index}", "fields": {"summary": title, "status": {"name": "Open"}}} for index, title in hits]}


@app.get("/testrail/index.php")
async def testrail(request: Request):
    raw = request.url.query
    path, _, rest = raw.partition("&")
    params = {key: values[0] for key, values in parse_qs(rest).items()}
    user = _user(request)
    _record("testrail", user, raw)
    await _latency("testrail")
    if not user:
        return JSONResponse({"error": "Authentication failed"}, status_code=401)
    if not re.fullmatch(r"/api/v2/get_cases/\d+", path):
        return JSONResponse({"error": "unsupported"}, status_code=400)
    hits = _matches(user, params.get("filter", ""))[: int(params.get("limit", 20))]
    offset = 100 * (_NAMES.index(user) if user in _NAMES else 0)
    return {"offset": 0, "limit": len(hits), "size": len(hits), "cases": [{"id": index + offset, "title": title} for index, title in hits]}


@app.get("/_mock/requests")
async def requests_log():
    return {"requests": REQUESTS}


@app.delete("/_mock/requests")
async def clear_log():
    REQUESTS.clear()
    return {"cleared": True}
