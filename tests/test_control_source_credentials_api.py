from __future__ import annotations

import sqlite3

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from fastapi.testclient import TestClient

from km_credentials.crypto import open_envelope
from src.km_control import ControlRegistry

SECRET = "alice-very-secret-pass"


def _env(monkeypatch, tmp_path, with_key=True):
    for key, value in {
        "KM_CONTROL_DB_URL": "sqlite:///" + str(tmp_path / "control.sqlite3"),
        "KM_CONTROL_SESSION_SIGNING_KEY": "c" * 32,
        "KM_ENTRY_SESSION_SIGNING_KEY": "b" * 32,
        "KM_DA40_PUBLIC_ORIGIN": "https://km-da40.example.test",
    }.items():
        monkeypatch.setenv(key, value)
    private = X25519PrivateKey.generate()
    if with_key:
        public = tmp_path / "k1.pub.pem"
        public.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        monkeypatch.setenv("KM_SOURCE_CREDENTIAL_KEY_ID", "k1")
        monkeypatch.setenv("KM_SOURCE_CREDENTIAL_PUBLIC_KEY_FILE", str(public))
    else:
        monkeypatch.delenv("KM_SOURCE_CREDENTIAL_KEY_ID", raising=False)
        monkeypatch.delenv("KM_SOURCE_CREDENTIAL_PUBLIC_KEY_FILE", raising=False)
    return private


def _active_user(client, username="operator"):
    registered = client.post("/api/auth/register", json={"username": username, "password": "strong-password-123"}).json()
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123") if not registry.list_users() or all(u.username != "admin" for u in registry.list_users()) else next(u for u in registry.list_users() if u.username == "admin")
    registry.set_user_status(admin.user_id, registered["user_id"], "active")
    assert client.post("/api/auth/login", json={"username": username, "password": "strong-password-123"}).status_code == 200
    return registered["user_id"], admin


def test_link_list_unlink_never_returns_secret(monkeypatch, tmp_path):
    private = _env(monkeypatch, tmp_path)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        user_id, _ = _active_user(client)
        assert client.get("/api/auth/source-credentials").json()["sources"] == [
            {"source": "confluence", "status": "not_linked"}, {"source": "jira", "status": "not_linked"}, {"source": "testrail", "status": "not_linked"}]
        linked = client.put("/api/auth/source-credentials/jira", json={"username": "alice", "secret": SECRET})
        assert linked.status_code == 200 and SECRET not in linked.text
        listed = client.get("/api/auth/source-credentials")
        assert listed.headers["cache-control"] == "no-store"
        assert SECRET not in listed.text and "envelope" not in listed.text
        jira = next(item for item in listed.json()["sources"] if item["source"] == "jira")
        assert jira["status"] == "active" and jira["username"] == "alice" and jira["auth_type"] == "basic"

        rows = sqlite3.connect(str(tmp_path / "control.sqlite3")).execute("SELECT secret_envelope FROM km_source_credentials").fetchall()
        assert len(rows) == 1 and SECRET not in rows[0][0]
        assert open_envelope({"k1": private}, rows[0][0], user_id, "jira").secret == SECRET
        audit = sqlite3.connect(str(tmp_path / "control.sqlite3")).execute("SELECT detail_json FROM km_audit_events WHERE event_type LIKE 'source_credential%'").fetchall()
        assert audit and all(SECRET not in row[0] for row in audit)

        assert client.delete("/api/auth/source-credentials/jira").json() == {"source": "jira", "status": "not_linked", "removed": True}
        assert sqlite3.connect(str(tmp_path / "control.sqlite3")).execute("SELECT COUNT(*) FROM km_source_credentials").fetchone()[0] == 0


def test_requires_login_and_known_source_and_masks_validation_errors(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        assert client.get("/api/auth/source-credentials").status_code == 401
        assert client.put("/api/auth/source-credentials/jira", json={"username": "a", "secret": SECRET}).status_code == 401
        _active_user(client)
        assert client.put("/api/auth/source-credentials/gitlab", json={"username": "a", "secret": SECRET}).status_code == 404
        invalid = client.put("/api/auth/source-credentials/jira", json={"username": "", "secret": SECRET, "auth_type": "basic"})
        assert invalid.status_code == 422 and SECRET not in invalid.text
        extra = client.put("/api/auth/source-credentials/jira", json={"username": "a", "secret": SECRET, "user_id": "someone-else"})
        assert extra.status_code == 422 and SECRET not in extra.text


def test_each_user_only_sees_and_changes_their_own(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as alice, TestClient(app, base_url="https://control.example.test") as bob:
        alice_id, _ = _active_user(alice, "alice")
        bob_id, _ = _active_user(bob, "bob")
        alice.put("/api/auth/source-credentials/confluence", json={"username": "alice", "secret": "a-secret-1"})
        bob.put("/api/auth/source-credentials/confluence", json={"username": "bob", "secret": "b-secret-1"})
        assert next(i for i in alice.get("/api/auth/source-credentials").json()["sources"] if i["source"] == "confluence")["username"] == "alice"
        assert next(i for i in bob.get("/api/auth/source-credentials").json()["sources"] if i["source"] == "confluence")["username"] == "bob"
        bob.delete("/api/auth/source-credentials/confluence")
        registry = ControlRegistry.from_environment()
        assert registry.source_credential_envelopes(alice_id, ["confluence"])["confluence"]["status"] == "active"
        assert registry.source_credential_envelopes(bob_id, ["confluence"])["confluence"]["status"] == "not_linked"


def test_unconfigured_key_fails_closed(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path, with_key=False)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        _active_user(client)
        response = client.put("/api/auth/source-credentials/jira", json={"username": "a", "secret": SECRET})
        assert response.status_code == 503 and SECRET not in response.text


def test_disabled_account_session_is_revoked_but_credentials_are_kept(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        user_id, admin = _active_user(client)
        client.put("/api/auth/source-credentials/jira", json={"username": "alice", "secret": SECRET})
        assert client.post("/api/auth/logout").status_code == 200
        assert client.get("/api/auth/source-credentials").status_code == 401
        registry = ControlRegistry.from_environment()
        assert registry.source_credential_envelopes(user_id, ["jira"])["jira"]["status"] == "active"
        assert client.post("/api/auth/login", json={"username": "operator", "password": "strong-password-123"}).status_code == 200
        assert next(i for i in client.get("/api/auth/source-credentials").json()["sources"] if i["source"] == "jira")["status"] == "active"
        registry.set_user_status(admin.user_id, user_id, "disabled")
        assert client.get("/api/auth/source-credentials").status_code == 401


def test_rejected_credential_is_marked_for_relink_until_user_updates(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        user_id, _ = _active_user(client)
        client.put("/api/auth/source-credentials/jira", json={"username": "alice", "secret": SECRET})
        registry = ControlRegistry.from_environment()
        registry.mark_source_credential_result(user_id, "jira", False, "source_rejected")
        assert registry.source_credential_envelopes(user_id, ["jira"])["jira"] == {"status": "needs_relink"}
        assert next(i for i in client.get("/api/auth/source-credentials").json()["sources"] if i["source"] == "jira")["status"] == "needs_relink"
        client.put("/api/auth/source-credentials/jira", json={"username": "alice", "secret": "new-" + SECRET})
        assert registry.source_credential_envelopes(user_id, ["jira"])["jira"]["status"] == "active"
