"""Query-through connectors for Confluence, Jira and TestRail.

Each call runs with the requesting user's own decrypted credential, which is
passed in per call and never stored on a module, client or connector object.
Endpoints, scopes and timeouts are configuration; TLS verification is always on.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import quote, urlencode, urlsplit

import httpx

from km_credentials.crypto import SourceSecret

# Lucene/CQL/JQL reserved characters are removed so user text can never change
# the query structure; the remaining text is placed inside a quoted literal.
_RESERVED = re.compile(r'[+\-&|!(){}\[\]^~*?:\\/"\']')
_SCOPE_KEY = re.compile(r"^[A-Za-z0-9_~.:-]{1,64}$")
_JIRA_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,31}-\d{1,9}$")


class SourceAuthError(Exception):
    """Source rejected the user's credential (401/403)."""


class SourceUnavailable(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SourceConfig:
    name: str
    base_url: str
    scopes: tuple[str, ...] = ()
    ca_file: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def origin(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}"


def load_source_config(name: str) -> SourceConfig | None:
    """`KM_CROSS_SEARCH_<NAME>_BASE_URL` (https only) and optional `_SCOPES`, `_CA_FILE`."""
    prefix = f"KM_CROSS_SEARCH_{name.upper()}_"
    base = os.getenv(prefix + "BASE_URL", "").strip().rstrip("/")
    if not base:
        return None
    parts = urlsplit(base)
    insecure_ok = os.getenv("KM_CROSS_SEARCH_ALLOW_HTTP_SOURCES", "false").lower() == "true"
    if parts.scheme != "https" and not (insecure_ok and parts.scheme == "http"):
        raise ValueError(f"{name} base URL must be https")
    scopes = tuple(value.strip() for value in os.getenv(prefix + "SCOPES", "").split(",") if value.strip())
    for scope in scopes:
        if not _SCOPE_KEY.fullmatch(scope):
            raise ValueError(f"{name} scope is invalid")
    return SourceConfig(name=name, base_url=base, scopes=scopes, ca_file=os.getenv(prefix + "CA_FILE", "").strip() or None)


def sanitize_text(query: str) -> str:
    text = " ".join(_RESERVED.sub(" ", query or "").split())
    return text[:200]


def _auth(secret: SourceSecret) -> tuple[httpx.Auth | None, dict]:
    if secret.auth_type == "bearer":
        return None, {"Authorization": "Bearer " + secret.secret}
    return httpx.BasicAuth(secret.username, secret.secret), {}


def _safe_external_url(config: SourceConfig, url: str | None) -> str | None:
    if not url or len(url) > 2048:
        return None
    parts = urlsplit(url)
    return url if f"{parts.scheme}://{parts.netloc}" == config.origin else None


async def _get(client: httpx.AsyncClient, url: str, secret: SourceSecret, timeout: float) -> object:
    auth, headers = _auth(secret)
    try:
        response = await client.get(url, auth=auth, headers={"Accept": "application/json", **headers}, timeout=timeout, follow_redirects=False)
    except httpx.TimeoutException:
        raise SourceUnavailable("timeout") from None
    except httpx.HTTPError:
        raise SourceUnavailable("unreachable") from None
    if response.status_code in (401, 403):
        raise SourceAuthError()
    if response.status_code != 200:
        raise SourceUnavailable(f"http_{response.status_code}")
    try:
        return response.json()
    except (ValueError, json.JSONDecodeError):
        raise SourceUnavailable("invalid_response") from None


def _hit(config: SourceConfig, object_id: str, title: str, snippet: str, url: str | None, rank: int) -> dict:
    title = (title or object_id)[:200]
    return {"sourceSystem": config.name, "objectId": f"{config.name}:{object_id}"[:160], "title": title,
            "snippet": (snippet or "")[:500], "url": _safe_external_url(config, url), "sourceRank": rank,
            "citation": {"source": title, "objectId": f"{config.name}:{object_id}"[:160]}}


async def search_confluence(client, config: SourceConfig, secret: SourceSecret, query: str, top_k: int, timeout: float) -> list[dict]:
    text = sanitize_text(query)
    if not text:
        return []
    cql = f'type = "page" AND text ~ "{text}"'
    if config.scopes:
        cql += " AND space in (" + ",".join(f'"{scope}"' for scope in config.scopes) + ")"
    url = f"{config.base_url}/rest/api/content/search?" + urlencode({"cql": cql, "limit": top_k, "expand": "space,version"})
    data = await _get(client, url, secret, timeout)
    results = []
    for rank, item in enumerate((data or {}).get("results", [])[:top_k], 1):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        page_id = str(item["id"])
        space = (item.get("space") or {}).get("key", "")
        results.append(_hit(config, page_id, str(item.get("title") or ""), f"Confluence {space}".strip(),
                            f"{config.base_url}/pages/viewpage.action?pageId={quote(page_id)}", rank))
    return results


async def search_jira(client, config: SourceConfig, secret: SourceSecret, query: str, top_k: int, timeout: float) -> list[dict]:
    raw = (query or "").strip()
    if _JIRA_KEY.fullmatch(raw):
        jql = f'key = "{raw}"'
    else:
        text = sanitize_text(raw)
        if not text:
            return []
        jql = f'text ~ "{text}"'
    if config.scopes:
        jql = f"({jql}) AND project in (" + ",".join(f'"{scope}"' for scope in config.scopes) + ")"
    url = f"{config.base_url}/rest/api/2/search?" + urlencode({"jql": jql + " ORDER BY updated DESC", "maxResults": top_k,
                                                                "fields": "summary,status,project,updated"})
    data = await _get(client, url, secret, timeout)
    results = []
    for rank, item in enumerate((data or {}).get("issues", [])[:top_k], 1):
        if not isinstance(item, dict) or not item.get("key"):
            continue
        fields = item.get("fields") or {}
        status = (fields.get("status") or {}).get("name", "")
        results.append(_hit(config, str(item["key"]), f"{item['key']} {fields.get('summary') or ''}".strip(),
                            f"Jira {status}".strip(), f"{config.base_url}/browse/{quote(str(item['key']))}", rank))
    return results


async def search_testrail(client, config: SourceConfig, secret: SourceSecret, query: str, top_k: int, timeout: float) -> list[dict]:
    """Server-side title filter per configured project[:suite]; never enumerates everything."""
    text = sanitize_text(query)
    if not text:
        return []
    if not config.scopes:
        raise SourceUnavailable("not_configured")
    results = []
    for scope in config.scopes:
        project, _, suite = scope.partition(":") if ":" in scope else (scope, "", "")
        if not project.isdigit() or (suite and not suite.isdigit()):
            raise SourceUnavailable("not_configured")
        params = {"filter": text, "limit": top_k}
        if suite:
            params["suite_id"] = suite
        url = f"{config.base_url}/index.php?/api/v2/get_cases/{project}&" + urlencode(params)
        data = await _get(client, url, secret, timeout)
        cases = data.get("cases", []) if isinstance(data, dict) else data
        for item in (cases or [])[:top_k]:
            if isinstance(item, dict) and item.get("id"):
                results.append(_hit(config, f"C{item['id']}", str(item.get("title") or ""), f"TestRail project {project}",
                                    f"{config.base_url}/index.php?/cases/view/{int(item['id'])}", len(results) + 1))
        if len(results) >= top_k:
            break
    return results[:top_k]


SEARCHERS = {"confluence": search_confluence, "jira": search_jira, "testrail": search_testrail}
