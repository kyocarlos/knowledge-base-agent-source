"""The anonymous identity: installed without the instance login, never replaces a real identity, can be switched off."""
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.base import BaseHTTPMiddleware

from src.web_api import anonymous_identity as anon


def _app():
    app = FastAPI()

    @app.get("/who")
    def who(request: Request):
        return {"identity": getattr(request.state, "km_identity", None)}
    return app


def test_it_gives_every_request_the_anonymous_identity_of_the_configured_instance(monkeypatch):
    monkeypatch.setattr(anon, "configured_instance_id", lambda: "da40")
    app = _app()
    assert anon.install_anonymous_identity(app) is True
    who = TestClient(app).get("/who").json()["identity"]
    assert who["sub"] == "anonymous" and who["instance_id"] == "da40" and who["anonymous"] is True


def test_it_can_be_switched_off_and_the_routes_see_no_identity(monkeypatch):
    monkeypatch.setenv("KM_ANONYMOUS_IDENTITY", "0")
    app = _app()
    anon.install_anonymous_identity(app)
    assert TestClient(app).get("/who").json()["identity"] is None


def test_it_is_not_installed_next_to_the_instance_login():
    app = _app()

    class InstanceAuthMiddleware(BaseHTTPMiddleware):       # the login middleware is recognised by its class name
        async def dispatch(self, request, call_next):
            return await call_next(request)
    app.add_middleware(InstanceAuthMiddleware)
    assert anon.install_anonymous_identity(app) is False
    assert TestClient(app).get("/who").json()["identity"] is None


def test_it_never_replaces_an_identity_that_is_already_there(monkeypatch):
    monkeypatch.setattr(anon, "configured_instance_id", lambda: "da40")
    app = _app()
    anon.install_anonymous_identity(app)

    async def with_identity(scope, receive, send):
        scope.setdefault("state", {})["km_identity"] = {"sub": "alice", "instance_id": "da40"}
        await app(scope, receive, send)
    assert TestClient(with_identity).get("/who").json()["identity"]["sub"] == "alice"


def test_auth_me_answers_the_reverse_proxy_session_check_with_the_anonymous_identity(monkeypatch):
    monkeypatch.setattr(anon, "configured_instance_id", lambda: "da40")
    app = FastAPI()
    anon.install_anonymous_identity(app)
    r = TestClient(app).get("/api/auth/me")
    assert r.status_code == 200 and r.json() == {"user_id": "anonymous", "instance_id": "da40", "role": "anonymous"}


def test_auth_me_answers_401_when_the_anonymous_identity_is_switched_off(monkeypatch):
    monkeypatch.setenv("KM_ANONYMOUS_IDENTITY", "0")
    app = FastAPI()
    anon.install_anonymous_identity(app)
    assert TestClient(app).get("/api/auth/me").status_code == 401


def test_auth_me_is_not_added_next_to_the_instance_login():
    app = FastAPI()

    class InstanceAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            return await call_next(request)
    app.add_middleware(InstanceAuthMiddleware)
    anon.install_anonymous_identity(app)
    assert TestClient(app).get("/api/auth/me").status_code == 404
