from __future__ import annotations

from fastapi.testclient import TestClient

from src.km_control import ControlRegistry
from src.oidc_control import OIDCSettings


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("KM_CONTROL_DB_URL", "sqlite:///" + str(tmp_path / "oidc.sqlite3"))
    monkeypatch.setenv("KM_CONTROL_SESSION_SIGNING_KEY", "c" * 32)
    monkeypatch.setenv("KM_ENTRY_SESSION_SIGNING_KEY", "e" * 32)
    monkeypatch.setenv("KM_OIDC_BINDING_SIGNING_KEY", "b" * 32)


def test_oidc_disabled_is_fail_closed(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("KM_OIDC_ENABLED", "false")
    from app.control_main import app
    with TestClient(app) as client:
        assert client.get("/oidc/login", follow_redirects=False).status_code == 503
        assert client.get("/oidc/availability").json() == {"enabled": False}


def test_public_jwks_is_available_for_client_registration_while_login_is_disabled(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("KM_OIDC_ENABLED", "false")
    jwks_path = tmp_path / "jwks.json"
    jwks_path.write_text('{"keys":[{"kty":"RSA","kid":"km-dev-1","use":"sig"}]}', encoding="utf-8")
    monkeypatch.setenv("KM_OIDC_CLIENT_JWKS_PATH", str(jwks_path))
    from app.control_main import app
    with TestClient(app) as client:
        response = client.get("/.well-known/km-oidc-client-jwks.json")
    assert response.status_code == 200
    assert response.json()["keys"][0]["kid"] == "km-dev-1"


def test_authorization_url_uses_state_nonce_and_pkce(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    values = {
        "KM_OIDC_ENABLED": "true", "KM_OIDC_ISSUER": "https://id.example.test",
        "KM_OIDC_AUTHORIZATION_ENDPOINT": "https://id.example.test/authorize",
        "KM_OIDC_TOKEN_ENDPOINT": "https://id.example.test/token", "KM_OIDC_JWKS_URI": "https://id.example.test/jwks",
        "KM_OIDC_CLIENT_ID": "km-client", "KM_OIDC_REDIRECT_URI": "https://km.example.test/oidc/callback",
        "KM_OIDC_POST_LOGOUT_REDIRECT_URI": "https://km.example.test/oidc/logout/callback",
    }
    for key, value in values.items(): monkeypatch.setenv(key, value)
    registry = ControlRegistry.from_environment()
    state, verifier, nonce = registry.create_oidc_transaction()
    url = OIDCSettings.from_environment().authorization_url(state, nonce, verifier)
    assert "code_challenge_method=S256" in url and f"state={state}" in url and f"nonce={nonce}" in url
    assert registry.consume_oidc_transaction(state) == (nonce, verifier)


def test_identity_binding_never_uses_email_or_account_automatically(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123")
    user = registry.register("existing-account", "strong-password-123")
    registry.set_user_status(admin.user_id, user.user_id, "active")
    identity = registry.upsert_external_identity("https://issuer.example.test", "immutable-subject", {"account": "existing-account", "email": "same@example.test"})
    assert identity["binding_status"] == "pending" and identity["user_id"] is None
    registry.verify_external_identity_local_account(identity["identity_id"], registry.authenticate("existing-account", "strong-password-123"))
    assert registry.get_external_identity(identity["identity_id"])["binding_status"] == "awaiting_approval"
    approved = registry.approve_external_identity(admin.user_id, identity["identity_id"])
    assert approved.user_id == user.user_id
    rebound = registry.upsert_external_identity("https://issuer.example.test", "immutable-subject", {"email": "changed@example.test"})
    assert rebound["binding_status"] == "bound" and rebound["user_id"] == user.user_id
