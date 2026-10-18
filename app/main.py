"""Production FastAPI entrypoint with a legacy compatibility layer."""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import AppSettings
from app.core.exceptions import install_exception_handlers
from app.core.logging import configure_logging
from app.core.trace import TraceMiddleware
from app.auth.oidc import AuthorizationStore
from app.auth.control import ControlStore
from app.auth.audit import AuthAudit
from app.api.oidc_routes import router as oidc_router
from src.web_api import app as legacy_app


_LEGACY_FRAMEWORK_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _add_legacy_compatibility_routes(app: FastAPI) -> None:
    for route in legacy_app.router.routes:
        if getattr(route, "path", None) not in _LEGACY_FRAMEWORK_PATHS:
            app.router.routes.append(route)

    for middleware in reversed(legacy_app.user_middleware):
        app.add_middleware(middleware.cls, **middleware.kwargs)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    resolved_settings = settings or AppSettings.from_env()
    configure_logging()
    app = FastAPI(
        title="Knowledge Base API",
        description="Versioned API contract with legacy Knowledge Base compatibility",
        version=resolved_settings.version,
        lifespan=legacy_app.router.lifespan_context,
    )
    app.state.settings = resolved_settings
    app.state.oidc_authorizations = AuthorizationStore()
    app.state.control_store = ControlStore(resolved_settings.oidc.control_db_path)
    app.state.auth_audit = AuthAudit()
    # Session middleware only stores a small signed identity marker; PKCE material stays server-side.
    app.add_middleware(SessionMiddleware, secret_key=resolved_settings.oidc.session_signing_key or "oidc-disabled", https_only=resolved_settings.oidc.enabled, same_site="lax")
    app.add_middleware(TraceMiddleware)
    install_exception_handlers(app)
    app.include_router(v1_router, prefix="/api/v1", tags=["Platform"])
    app.include_router(oidc_router)
    _add_legacy_compatibility_routes(app)
    return app


app = create_app()
