"""Production FastAPI entrypoint with a legacy compatibility layer."""

from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.router import router as v1_router
from app.core.config import AppSettings
from app.core.exceptions import install_exception_handlers
from app.core.logging import configure_logging
from app.core.trace import TraceMiddleware
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
    app.add_middleware(TraceMiddleware)
    install_exception_handlers(app)
    app.include_router(v1_router, prefix="/api/v1", tags=["Platform"])
    _add_legacy_compatibility_routes(app)
    return app


app = create_app()
