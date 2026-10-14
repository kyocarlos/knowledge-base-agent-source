"""Public OIDC routes.  Admin binding approval deliberately has no public HTTP route."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import secrets
from urllib.parse import parse_qs, urlparse

from app.auth.oidc import OIDCClient, OIDCError
from app.auth.oidc import map_claims

router = APIRouter(tags=["KM Control Auth"])


def _client(request: Request) -> OIDCClient:
    return OIDCClient(request.app.state.settings.oidc, request.app.state.oidc_authorizations)


@router.get("/auth/oidc/login", include_in_schema=True)
async def login(request: Request):
    try:
        location = _client(request).authorization_redirect()
        state = parse_qs(urlparse(location).query)["state"][0]
        request.session["oidc_state"] = state
        response = RedirectResponse(location, status_code=302)
        request.app.state.auth_audit.record("login_started")
        return response
    except OIDCError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/oidc/callback", include_in_schema=True)
async def callback(request: Request, code: str = "", state: str = ""):
    try:
        session_state = request.session.pop("oidc_state", "")
        if not isinstance(session_state, str) or not secrets.compare_digest(session_state, state):
            raise OIDCError("OIDC state does not match this browser session")
        claims = _client(request).exchange_and_validate(code=code, state=state)
    except OIDCError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    identity = map_claims(claims, request.app.state.settings.oidc.claim_mapping)
    control = request.app.state.control_store
    status = control.binding_status(claims["iss"], claims["sub"])
    if status is None:
        control.create_pending_binding(claims["iss"], claims["sub"], identity["user_id"])
        request.app.state.auth_audit.record("binding_pending", issuer=claims["iss"])
        raise HTTPException(status_code=403, detail="identity binding requires manual approval")
    if status != "approved":
        request.app.state.auth_audit.record("binding_denied", issuer=claims["iss"])
        raise HTTPException(status_code=403, detail="identity binding is not approved")
    request.session["oidc_identity"] = {"iss": claims["iss"], "sub": claims["sub"], "user_id": identity["user_id"]}
    request.app.state.auth_audit.record("login_succeeded", issuer=claims["iss"])
    return RedirectResponse("/", status_code=303)


@router.post("/auth/logout", status_code=303, include_in_schema=True)
async def logout(request: Request):
    request.session.clear()
    request.app.state.auth_audit.record("logout")
    return RedirectResponse("/auth/signed-out", status_code=303)


@router.get("/auth/signed-out", include_in_schema=True)
async def signed_out():
    return HTMLResponse("<h1>Signed out</h1><p>Your KM local session has ended.</p>")


@router.get("/auth/oidc/logout/callback", include_in_schema=True)
async def logout_callback(request: Request):
    """Reserved redirect target for a future RP-initiated logout integration."""
    request.session.clear()
    request.app.state.auth_audit.record("logout_redirect")
    return RedirectResponse("/auth/signed-out", status_code=303)
