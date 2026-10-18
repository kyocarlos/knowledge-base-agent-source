from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.auth.control import ControlStore, effective_grants
from app.auth.oidc import AuthorizationStore, OIDCClient, OIDCError, map_claims, pkce_challenge
from app.core.config import AppSettings, OIDCSettings
from app.main import create_app


def settings(tmp_path) -> OIDCSettings:
    return OIDCSettings(
        enabled=True, issuer="https://identity.example.test", client_id="km-dev-client",
        client_secret="not-a-real-secret", redirect_uri="https://km-dev.example.test/oidc/callback",
        session_signing_key="x" * 32, control_db_path=str(tmp_path / "control.sqlite3"),
    )


def test_login_uses_unique_state_nonce_and_s256_pkce(tmp_path):
    client = OIDCClient(settings(tmp_path), AuthorizationStore())
    first, second = client.authorization_redirect(), client.authorization_redirect()
    a, b = parse_qs(urlparse(first).query), parse_qs(urlparse(second).query)
    assert a["state"] != b["state"]
    assert a["nonce"] != b["nonce"]
    assert a["code_challenge_method"] == ["S256"]
    assert len(a["code_challenge"][0]) == 43
    assert "client_secret" not in first


def test_state_is_single_use_and_explicitly_rejected(tmp_path):
    client = OIDCClient(settings(tmp_path), AuthorizationStore())
    state = parse_qs(urlparse(client.authorization_redirect()).query)["state"][0]
    client.store.consume(state)
    with pytest.raises(OIDCError, match="invalid or expired"):
        client.store.consume(state)


def test_config_requires_real_values_only_when_enabled(monkeypatch):
    monkeypatch.delenv("KM_OIDC_ENABLED", raising=False)
    assert AppSettings.from_env().oidc.enabled is False
    monkeypatch.setenv("KM_OIDC_ENABLED", "true")
    with pytest.raises(ValueError, match="HTTPS URL"):
        AppSettings.from_env()


def test_disabled_routes_fail_closed(tmp_path):
    app = create_app(AppSettings(environment="test", oidc=OIDCSettings(control_db_path=str(tmp_path / "control.sqlite3"))))
    with TestClient(app) as client:
        response = client.get("/auth/oidc/login", follow_redirects=False)
    assert response.status_code == 503


def test_callback_requires_the_same_browser_session_state(tmp_path):
    app = create_app(AppSettings(environment="test", oidc=settings(tmp_path)))
    with TestClient(app) as client:
        response = client.get("/oidc/callback?code=unused&state=from-another-browser", follow_redirects=False)
    assert response.status_code == 401


def test_local_logout_and_future_logout_redirect_are_local_only(tmp_path):
    app = create_app(AppSettings(environment="test", oidc=settings(tmp_path)))
    with TestClient(app) as client:
        logout = client.post("/auth/logout", follow_redirects=False)
        redirect = client.get("/auth/oidc/logout/callback", follow_redirects=False)
        signed_out = client.get("/auth/signed-out")
    assert logout.headers["location"] == "/auth/signed-out"
    assert redirect.headers["location"] == "/auth/signed-out"
    assert signed_out.status_code == 200


def test_claim_mapping_and_manual_binding_control_db(tmp_path):
    mapped = map_claims({"sub": "subject-1", "mail": "a@example.test"}, (("user_id", "sub"), ("email", "mail")))
    assert mapped == {"user_id": "subject-1", "email": "a@example.test"}
    store = ControlStore(str(tmp_path / "control.sqlite3"))
    store.create_pending_binding("https://issuer.test", "subject-1", "local-user")
    assert store.binding_status("https://issuer.test", "subject-1") == "pending"
    store.approve_binding("https://issuer.test", "subject-1", "control-admin")
    assert store.binding_status("https://issuer.test", "subject-1") == "approved"


def test_control_grants_add_to_but_do_not_replace_local_grants(tmp_path):
    store = ControlStore(str(tmp_path / "control.sqlite3"))
    with store._connect() as db:
        db.execute("INSERT INTO grants(user_id,permission) VALUES (?,?)", ("u1", "reports:review"))
    assert effective_grants(store, "u1", {"search:read"}) == {"search:read", "reports:review"}
