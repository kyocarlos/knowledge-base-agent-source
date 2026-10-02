"""Public KM Control authentication endpoints; independent of KM business APIs."""
from __future__ import annotations

import os
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .instance_isolation import VALID_INSTANCE_IDS
from .km_control import (
    ControlAuthenticationError,
    ControlAuthorizationError,
    ControlError,
    ControlRegistry,
    issue_control_session,
    issue_oidc_binding_session,
    verify_control_session,
    verify_oidc_binding_session,
)
from .oidc_control import OIDCError, OIDCSettings, read_client_jwks

CONTROL_COOKIE = "km_control_session"
BINDING_COOKIE = "km_oidc_binding"
router = APIRouter(prefix="/api/auth", tags=["KM control authentication"])
oidc_router = APIRouter(tags=["KM OIDC control authentication"])


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=1024)


class InstanceSelection(BaseModel):
    instance_id: str


class AdminCreateUser(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=1024)
    role: str = Field(default="user", pattern="^(user|admin)$")


def _enabled_instance_ids() -> frozenset[str]:
    """Return deployment-enabled entries, never a client-selected scope."""
    configured = os.getenv("KM_ENABLED_INSTANCE_IDS", "test,da40,rd2")
    values = frozenset(value.strip().lower() for value in configured.split(",") if value.strip())
    if not values or not values.issubset(VALID_INSTANCE_IDS):
        raise HTTPException(status_code=503, detail="KM enabled-instance configuration is invalid")
    return values


def _control_cookie_path() -> str:
    path = os.getenv("KM_CONTROL_COOKIE_PATH", "/").strip()
    if not path.startswith("/"):
        raise HTTPException(status_code=503, detail="KM Control cookie path is invalid")
    return path


def _visible_grants(user_id: str) -> list[dict]:
    enabled = _enabled_instance_ids()
    return [grant for grant in ControlRegistry.from_environment().grants_for(user_id) if grant["instance_id"] in enabled]


def _identity(request: Request) -> dict:
    try:
        return verify_control_session(request.cookies.get(CONTROL_COOKIE, ""))
    except (ControlError, ControlAuthenticationError) as exc:
        raise HTTPException(status_code=401, detail="KM Control login required") from exc


def _admin(request: Request) -> dict:
    claims = _identity(request)
    if not claims.get("admin"):
        raise HTTPException(status_code=403, detail="KM Control admin role required")
    return claims


def _oidc_settings() -> OIDCSettings:
    try:
        return OIDCSettings.from_environment()
    except OIDCError as exc:
        raise HTTPException(status_code=503, detail="OIDC is not configured") from exc


def _clear_km_cookies(response: Response) -> None:
    response.delete_cookie(CONTROL_COOKIE, path=_control_cookie_path())
    response.delete_cookie(BINDING_COOKIE, path=_control_cookie_path())
    response.delete_cookie("km_entry_session", path="/")
    response.delete_cookie("km_instance_route", path="/")


def _binding_identity(request: Request) -> dict:
    try:
        claims = verify_oidc_binding_session(request.cookies.get(BINDING_COOKIE, ""))
    except (ControlError, ControlAuthenticationError) as exc:
        raise HTTPException(status_code=401, detail="OIDC binding verification required") from exc
    identity = ControlRegistry.from_environment().get_external_identity(str(claims["identity_id"]))
    if not identity:
        raise HTTPException(status_code=401, detail="OIDC identity not found")
    return identity


@router.post("/register", status_code=201)
async def register(payload: Credentials):
    try:
        user = ControlRegistry.from_environment().register(payload.username, payload.password)
    except ControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user_id": user.user_id, "username": user.username, "status": user.status}


@router.post("/login")
async def login(payload: Credentials, response: Response):
    try:
        user = ControlRegistry.from_environment().authenticate(payload.username, payload.password)
        response.set_cookie(CONTROL_COOKIE, issue_control_session(user), httponly=True, secure=True, samesite="strict", max_age=8 * 60 * 60, path=_control_cookie_path())
        return {"user_id": user.user_id, "username": user.username, "is_admin": user.is_admin, "instances": _visible_grants(user.user_id), "enabled_instances": sorted(_enabled_instance_ids())}
    except ControlAuthenticationError as exc:
        raise HTTPException(status_code=401, detail="invalid username or password") from exc
    except ControlAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="account pending approval or disabled") from exc


@router.post("/logout")
async def logout(response: Response):
    _clear_km_cookies(response)
    return {"status": "logged_out"}


@oidc_router.get("/oidc/login", include_in_schema=False)
async def oidc_login():
    settings = _oidc_settings()
    state, verifier, nonce = ControlRegistry.from_environment().create_oidc_transaction()
    return RedirectResponse(settings.authorization_url(state, nonce, verifier), status_code=302, headers={"Cache-Control": "no-store"})


@oidc_router.get("/oidc/availability", include_in_schema=False)
async def oidc_availability():
    """Expose only whether the future sign-in option is usable; no IdP metadata."""
    try:
        _oidc_settings()
    except HTTPException:
        return {"enabled": False}
    return {"enabled": True}


@oidc_router.get("/.well-known/km-oidc-client-jwks.json", include_in_schema=False)
async def oidc_client_jwks():
    try:
        return read_client_jwks()
    except OIDCError as exc:
        raise HTTPException(status_code=503, detail="OIDC client JWKS is not configured") from exc


@oidc_router.get("/oidc/callback", include_in_schema=False)
async def oidc_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error or not code or not state:
        raise HTTPException(status_code=401, detail="OIDC authorization was denied")
    settings = _oidc_settings()
    registry = ControlRegistry.from_environment()
    try:
        nonce, verifier = registry.consume_oidc_transaction(state)
        tokens = settings.exchange_code(code, verifier)
        claims = settings.validate_id_token(tokens["id_token"], nonce)
        identity = registry.upsert_external_identity(settings.issuer, str(claims["sub"]), settings.profile(claims))
    except (OIDCError, ControlError, ControlAuthenticationError) as exc:
        raise HTTPException(status_code=401, detail="OIDC authentication failed") from exc
    if identity["binding_status"] == "bound" and identity["user_id"]:
        user = registry.get_user(str(identity["user_id"]))
        if user and user.status == "active":
            response = RedirectResponse(url="/login.html", status_code=303)
            response.set_cookie(CONTROL_COOKIE, issue_control_session(user), httponly=True, secure=True, samesite="strict", max_age=8 * 60 * 60, path=_control_cookie_path())
            return response
    response = RedirectResponse(url="/oidc/binding.html", status_code=303)
    response.set_cookie(BINDING_COOKIE, issue_oidc_binding_session(str(identity["identity_id"])), httponly=True, secure=True, samesite="strict", max_age=10 * 60, path=_control_cookie_path())
    return response


@oidc_router.get("/signed-out", include_in_schema=False)
async def signed_out():
    return HTMLResponse("<!doctype html><html lang='zh-Hant'><title>KM 已登出</title><body><h1>KM 已登出</h1><p>已結束 KM 工作階段。</p><a href='/login.html'>返回 KM 登入</a></body></html>", headers={"Cache-Control": "no-store"})


@oidc_router.get("/oidc/logout", include_in_schema=False)
async def oidc_logout(shared: bool = False):
    response: Response
    if shared:
        settings = _oidc_settings()
        if not settings.end_session_endpoint:
            raise HTTPException(status_code=503, detail="Shared Identity logout is not configured")
        # The IdP session is only ended by an explicit request. id_token_hint is
        # intentionally deferred until encrypted token-session storage is enabled.
        response = RedirectResponse(f"{settings.end_session_endpoint}?{urlencode({'post_logout_redirect_uri': settings.post_logout_redirect_uri, 'state': secrets.token_urlsafe(24)})}", status_code=302)
    else:
        response = RedirectResponse(url="/signed-out", status_code=303)
    _clear_km_cookies(response)
    return response


@oidc_router.get("/oidc/logout/callback", include_in_schema=False)
async def oidc_logout_callback():
    response = RedirectResponse(url="/signed-out", status_code=303)
    _clear_km_cookies(response)
    return response


@router.get("/api/auth/oidc/binding")
async def oidc_binding_status(request: Request):
    identity = _binding_identity(request)
    return {"identity_id": identity["identity_id"], "status": identity["binding_status"]}


@router.post("/api/auth/oidc/binding/verify")
async def oidc_binding_verify(payload: Credentials, request: Request):
    identity = _binding_identity(request)
    try:
        user = ControlRegistry.from_environment().authenticate(payload.username, payload.password)
        ControlRegistry.from_environment().verify_external_identity_local_account(str(identity["identity_id"]), user)
    except (ControlError, ControlAuthenticationError, ControlAuthorizationError) as exc:
        raise HTTPException(status_code=401, detail="local KM account verification failed") from exc
    return {"status": "awaiting_approval"}


@router.get("/api/auth/admin/oidc-bindings")
async def list_oidc_bindings(request: Request):
    _admin(request)
    identities = ControlRegistry.from_environment().list_external_identities(only_pending=True)
    return {"bindings": [{key: item[key] for key in ("identity_id", "binding_status", "user_id", "provider_issuer", "requested_at", "verified_at")} for item in identities]}


@router.post("/api/auth/admin/oidc-bindings/{identity_id}/approve")
async def approve_oidc_binding(identity_id: str, request: Request):
    admin = _admin(request)
    try:
        user = ControlRegistry.from_environment().approve_external_identity(str(admin["sub"]), identity_id)
    except ControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"identity_id": identity_id, "user_id": user.user_id, "status": "bound"}


@router.get("/me")
async def me(request: Request):
    claims = _identity(request)
    return {"user_id": claims["sub"], "is_admin": bool(claims.get("admin")), "instances": _visible_grants(claims["sub"]), "enabled_instances": sorted(_enabled_instance_ids())}


@router.post("/select-instance")
async def select_instance(payload: InstanceSelection, request: Request, return_to: str | None = None):
    if payload.instance_id not in _enabled_instance_ids():
        raise HTTPException(status_code=422, detail="KM instance is not enabled")
    claims = _identity(request)
    user = ControlRegistry.from_environment().get_user(claims["sub"])
    if not user or user.session_epoch != int(claims["epoch"]):
        raise HTTPException(status_code=401, detail="session revoked")
    try:
        code = ControlRegistry.from_environment().create_login_code(user, payload.instance_id)
    except ControlAuthorizationError as exc:
        raise HTTPException(status_code=403, detail="instance is not granted") from exc
    origin = os.getenv(f"KM_{payload.instance_id.upper()}_PUBLIC_ORIGIN", "").rstrip("/")
    if not origin.startswith("https://"):
        raise HTTPException(status_code=503, detail="target KM origin is not configured")
    callback_query = {"code": code}
    if return_to:
        callback_query["return_to"] = return_to
    return {"redirect_url": f"{origin}/api/auth/callback?{urlencode(callback_query)}"}


@router.put("/admin/users/{user_id}/status")
async def set_status(user_id: str, payload: dict, request: Request):
    admin = _admin(request)
    try:
        user = ControlRegistry.from_environment().set_user_status(admin["sub"], user_id, str(payload.get("status", "")))
    except ControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user_id": user.user_id, "status": user.status}


@router.get("/admin/users")
async def list_users(request: Request):
    _admin(request)
    registry = ControlRegistry.from_environment()
    enabled = _enabled_instance_ids()
    return {"enabled_instances": sorted(enabled), "users": [{**user.__dict__, "instances": [grant for grant in registry.grants_for(user.user_id) if grant["instance_id"] in enabled]} for user in registry.list_users()]}


@router.post("/admin/users", status_code=201)
async def create_user(payload: AdminCreateUser, request: Request):
    admin = _admin(request)
    if "test" not in _enabled_instance_ids():
        raise HTTPException(status_code=503, detail="Test instance is not enabled")
    try:
        user = ControlRegistry.from_environment().create_active_with_grant(admin["sub"], payload.username, payload.password, payload.role, "test")
    except ControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user_id": user.user_id, "username": user.username, "status": user.status, "is_admin": user.is_admin, "instances": [{"instance_id": "test", "role": payload.role}]}


@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, request: Request):
    admin = _admin(request)
    try:
        user = ControlRegistry.from_environment().delete_user(admin["sub"], user_id)
    except ControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user_id": user.user_id, "status": user.status, "instances": []}


@router.delete("/admin/users/{user_id}/permanent")
async def permanently_delete_user(user_id: str, request: Request):
    admin = _admin(request)
    try:
        ControlRegistry.from_environment().permanently_delete_user(admin["sub"], user_id)
    except ControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user_id": user_id, "deleted": True}


@router.put("/admin/users/{user_id}/grants/{instance_id}")
async def grant(user_id: str, instance_id: str, payload: dict, request: Request):
    admin = _admin(request)
    if instance_id not in _enabled_instance_ids():
        raise HTTPException(status_code=422, detail="KM instance is not enabled")
    try:
        ControlRegistry.from_environment().grant(admin["sub"], user_id, instance_id, str(payload.get("role", "user")))
    except ControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user_id": user_id, "instances": _visible_grants(user_id)}


@router.delete("/admin/users/{user_id}/grants/{instance_id}")
async def revoke_grant(user_id: str, instance_id: str, request: Request):
    admin = _admin(request)
    if instance_id not in _enabled_instance_ids():
        raise HTTPException(status_code=422, detail="KM instance is not enabled")
    try:
        ControlRegistry.from_environment().revoke_grant(admin["sub"], user_id, instance_id)
    except ControlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"user_id": user_id, "instances": _visible_grants(user_id)}
