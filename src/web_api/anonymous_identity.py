"""An anonymous identity for deployments that run without the instance login.

Most routes (UI upload, zone pages, keeper, Wi-Fi8, RCA, CSIT assistants, legacy pages) read request.state.km_identity, which the instance login
(InstanceAuthMiddleware) used to set. Without it every one of them answers 401. This middleware gives each request the same anonymous identity bound
to the configured instance, so the application works without a login.

It is installed only when the instance login is not. KM_ANONYMOUS_IDENTITY=0 switches it off again (the routes then answer 401 as before).
Everyone who can reach the service shares the identity "anonymous": per-user state (histories, rate limits) is shared, and nothing here limits who may call.
"""
import logging
import os

from starlette.middleware.base import BaseHTTPMiddleware

from ..instance_isolation import configured_instance_id

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return os.getenv("KM_ANONYMOUS_IDENTITY", "1").strip().lower() not in {"0", "false", "no", "off"}


def anonymous_identity() -> dict:
    return {"sub": "anonymous", "instance_id": configured_instance_id() or "", "role": "anonymous", "epoch": 0, "anonymous": True}


class AnonymousIdentityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if enabled() and not getattr(request.state, "km_identity", None):   # a real identity set earlier is never replaced
            request.state.km_identity = anonymous_identity()
        return await call_next(request)


def install_anonymous_identity(app) -> bool:
    """Add the middleware unless the instance login is installed. Returns whether it was added."""
    if any(getattr(m.cls, "__name__", "") == "InstanceAuthMiddleware" for m in app.user_middleware):
        return False
    app.add_middleware(AnonymousIdentityMiddleware)
    if enabled():
        logger.warning("KM instance login is not installed: every request uses the anonymous identity (set KM_ANONYMOUS_IDENTITY=0 to refuse instead)")
    return True
