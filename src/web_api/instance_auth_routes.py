"""Data-plane session callback and fail-closed Control DB grant guard."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..instance_isolation import configured_instance_id
from ..km_control import ControlAuthenticationError, ControlAuthorizationError, ControlError, ControlRegistry, issue_entry_session, verify_entry_session

SESSION_COOKIE = "km_entry_session"
DEFAULT_RETURN_PATH = "/chat-v2.html"
ALLOWED_RETURN_PATHS = frozenset({
    "/",
    "/upload",
    "/admin",
    "/admin/chunks",
    "/admin/report-reviews",
    "/skills",
    "/chat-v2.html",
})
# Only health and the one-time entry callback are public.  Nginx serves the
# login page; every data-bearing HTTP route is authenticated here as well.
PUBLIC_PATHS = frozenset({"/health", "/api/auth/callback", "/api/auth/login-url"})
router = APIRouter(prefix="/api/auth", tags=["KM data-plane authorization"])


def safe_return_path(value: str | None) -> str:
    """Return only a same-origin, known KM frontend path after login."""
    if not value:
        return DEFAULT_RETURN_PATH
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or parsed.path not in ALLOWED_RETURN_PATHS:
        return DEFAULT_RETURN_PATH
    return parsed.path


def _instance_id() -> str:
    value = configured_instance_id()
    if not value:
        raise HTTPException(status_code=503, detail="KM instance isolation is not configured")
    return value


def _identity(request: Request) -> dict:
    identity = getattr(request.state, "km_identity", None)
    if not identity:
        raise HTTPException(status_code=401, detail="KM login required")
    return identity


class InstanceAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        instance_id = configured_instance_id()
        if not instance_id:
            return await call_next(request)
        path = request.url.path
        if path in PUBLIC_PATHS:
            return await call_next(request)
        try:
            claims = verify_entry_session(request.cookies.get(SESSION_COOKIE, ""), instance_id)
            ControlRegistry.from_environment().validate_entry_claims(claims["sub"], instance_id, claims["role"], claims["epoch"])
            request.state.km_identity = claims
        except (ControlError, ControlAuthenticationError, ControlAuthorizationError):
            return Response(status_code=401, content='{"detail":"KM instance authorization required"}', media_type="application/json")
        return await call_next(request)


@router.get("/login-url")
async def login_url():
    origin = os.getenv("KM_CONTROL_PUBLIC_ORIGIN", "").rstrip("/")
    if not origin.startswith("https://"):
        raise HTTPException(status_code=503, detail="KM Control origin is not configured")
    return {"login_url": origin + "/control-login.html"}


@router.get("/callback")
async def callback(code: str, return_to: str | None = None):
    instance_id = _instance_id()
    try:
        user, role = ControlRegistry.from_environment().consume_login_code(code, instance_id)
        response = RedirectResponse(url=safe_return_path(return_to), status_code=303)
        response.set_cookie(SESSION_COOKIE, issue_entry_session(user.user_id, instance_id, role, user.session_epoch), httponly=True, secure=True, samesite="strict", max_age=15 * 60, path="/")
        return response
    except (ControlError, ControlAuthenticationError, ControlAuthorizationError):
        raise HTTPException(status_code=401, detail="invalid or expired KM entry code")


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"status": "logged_out"}


@router.get("/me")
async def me(request: Request):
    identity = _identity(request)
    return {"user_id": identity["sub"], "instance_id": identity["instance_id"], "role": identity["role"]}
