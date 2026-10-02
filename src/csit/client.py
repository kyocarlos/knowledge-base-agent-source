"""Minimal read-only CSIT HTTP adapter.

Authentication is deliberately supplied by the caller. This module never
loads, stores, or logs a CSIT credential.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from typing import Protocol
from typing import Any
from urllib.parse import quote

import httpx

from .contract import CsitContract

_PLACEHOLDER = re.compile(r"\{([^{}]+)\}")
KM_MANIFEST_PATH = "/api/km/v1/projects/{projectId}/manifest"


class CsitRequestError(RuntimeError):
    """Sanitized CSIT request failure."""


class AuthProvider(Protocol):
    """Provide request headers without owning a CSIT credential lifecycle."""

    def headers(self) -> Mapping[str, str]:
        """Return headers for one request; values are never logged by this adapter."""


class StaticHeaderAuthProvider:
    """Small test/integration adapter for caller-owned, already-approved headers."""

    def __init__(self, headers: Mapping[str, str]) -> None:
        self._headers = dict(headers)

    def headers(self) -> Mapping[str, str]:
        return dict(self._headers)


class CsitReadOnlyClient:
    """Execute only mapped GET endpoints from a CSIT contract."""

    def __init__(
        self,
        base_url: str,
        contract: CsitContract,
        *,
        headers: Mapping[str, str] | None = None,
        auth_provider: AuthProvider | None = None,
        timeout: float = 20.0,
        verify: str | bool = True,
        username: str | None = None,
        password: str | None = None,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not base_url.strip():
            raise ValueError("CSIT base_url is required")
        self._contract = contract
        self._base_url = base_url.rstrip("/")
        if headers is not None and auth_provider is not None:
            raise ValueError("provide headers or auth_provider, not both")
        self._auth_provider = auth_provider
        self._headers = dict(headers or {})
        self._username = username
        self._password = password
        if (username is None) != (password is None):
            raise ValueError("CSIT username and password must be supplied together")
        self._session_lock = threading.RLock()
        self._logged_in = False
        self._client = httpx.Client(
            timeout=timeout,
            verify=verify,
            transport=http_transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CsitReadOnlyClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get(
        self,
        path: str,
        *,
        path_params: Mapping[str, object] | None = None,
        query: Mapping[str, object] | None = None,
    ) -> Any:
        endpoint = self._contract.endpoint(path, "GET")
        rendered_path = self._render_path(endpoint.path, path_params or {})
        try:
            response = self._request_get(endpoint, rendered_path, query=query)
            response.raise_for_status()
            if not response.content.strip():
                raise CsitRequestError("CSIT GET returned an empty response")
            payload = response.json()
            if payload is None:
                raise CsitRequestError("CSIT GET returned an empty JSON response")
            return payload
        except httpx.HTTPStatusError as exc:
            raise CsitRequestError(f"CSIT GET failed with HTTP {exc.response.status_code}") from None
        except CsitRequestError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise CsitRequestError(f"CSIT GET failed: {type(exc).__name__}") from None

    def download(
        self,
        path: str,
        *,
        path_params: Mapping[str, object] | None = None,
    ) -> httpx.Response:
        """Return a read-only binary response; caller must close it."""

        endpoint = self._contract.endpoint(path, "GET")
        rendered_path = self._render_path(endpoint.path, path_params or {})
        try:
            response = self._request_get(endpoint, rendered_path)
            response.raise_for_status()
            if not response.content:
                raise CsitRequestError("CSIT download returned an empty response")
            return response
        except httpx.HTTPStatusError as exc:
            raise CsitRequestError(f"CSIT download failed with HTTP {exc.response.status_code}") from None
        except CsitRequestError:
            raise
        except httpx.HTTPError as exc:
            raise CsitRequestError(f"CSIT download failed: {type(exc).__name__}") from None

    def get_km_manifest(self, project_id: str) -> Any:
        """Fetch the dedicated KM V1 manifest endpoint, never a File DTO."""
        project_id = str(project_id or "").strip()
        if not project_id:
            raise CsitRequestError("CSIT KM manifest requires projectId")
        rendered_path = self._render_path(KM_MANIFEST_PATH, {"projectId": project_id})
        try:
            response = self._request_get(None, rendered_path)
            response.raise_for_status()
            if not response.content.strip():
                raise CsitRequestError("CSIT KM manifest returned an empty response")
            payload = response.json()
            if payload is None:
                raise CsitRequestError("CSIT KM manifest returned an empty JSON response")
            return payload
        except httpx.HTTPStatusError as exc:
            raise CsitRequestError(f"CSIT KM manifest failed with HTTP {exc.response.status_code}") from None
        except CsitRequestError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise CsitRequestError(f"CSIT KM manifest failed: {type(exc).__name__}") from None

    def _request_get(self, endpoint: Any, rendered_path: str, *, query: Mapping[str, object] | None = None) -> httpx.Response:
        with self._session_lock:
            request_headers = dict(self._headers)
            if self._auth_provider is not None:
                request_headers.update(self._auth_provider.headers())
            if self._username is not None and not self._logged_in:
                self._login(request_headers)
            response = self._client.get(
                f"{self._base_url}{rendered_path}",
                params={key: value for key, value in (query or {}).items() if value is not None},
                headers=request_headers,
            )
            if response.status_code == 401 and self._username is not None:
                self._logged_in = False
                self._login(request_headers)
                response = self._client.get(
                    f"{self._base_url}{rendered_path}",
                    params={key: value for key, value in (query or {}).items() if value is not None},
                    headers=request_headers,
                )
            return response

    def _login(self, request_headers: Mapping[str, str]) -> None:
        if self._username is None or self._password is None:
            raise CsitRequestError("CSIT session credentials are not configured")
        try:
            response = self._client.post(
                f"{self._base_url}/auth/login",
                data={"username": self._username, "password": self._password},
                headers={"Content-Type": "application/x-www-form-urlencoded", **request_headers},
            )
            if response.status_code not in {200, 204, 301, 302, 303, 307, 308}:
                raise CsitRequestError(f"CSIT login failed with HTTP {response.status_code}")
            if not self._client.cookies:
                raise CsitRequestError("CSIT login did not return a session cookie")
            self._logged_in = True
        except CsitRequestError:
            raise
        except httpx.HTTPError as exc:
            raise CsitRequestError(f"CSIT login failed: {type(exc).__name__}") from None

    def request(self, method: str, path: str, **_: object) -> Any:
        """Fail closed for future callers that try to use a write verb."""

        if method.upper() != "GET":
            raise CsitRequestError("CSIT read-only adapter rejects non-GET requests")
        return self.get(path)

    @staticmethod
    def _render_path(path: str, values: Mapping[str, object]) -> str:
        def replace(match: re.Match[str]) -> str:
            raw_name = match.group(1)
            name = raw_name.split(":", 1)[0]
            if name not in values:
                raise CsitRequestError(f"CSIT path parameter missing: {name}")
            return quote(str(values[name]), safe="")

        return _PLACEHOLDER.sub(replace, path)
