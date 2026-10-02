from __future__ import annotations

from pathlib import Path

import pytest

from src.instance_isolation import InstanceIsolationError, InstanceStoreConfig, redis_key
from src.km_control import ControlAuthenticationError, ControlAuthorizationError, ControlRegistry, issue_control_session, issue_entry_session, verify_entry_session


def _instance_env(monkeypatch, tmp_path: Path, instance_id: str = "test") -> None:
    values = {
        "KM_INSTANCE_ID": instance_id, "NEO4J_URI": "bolt://neo4j:7687", "QDRANT_URL": "http://qdrant:6333", "TIMESCALEDB_URL": "postgresql://timescaledb/km",
        "KB_REPORT_REGISTRY_URL": "sqlite:///" + str(tmp_path / "registry.sqlite3"), "REDIS_URL": "redis://redis:6379/0", "KM_REDIS_KEY_PREFIX": f"km:{instance_id}:",
        "KB_INGEST_UPLOAD_ROOT": str(tmp_path / "uploads"), "KB_REPORT_STAGING_ROOT": str(tmp_path / "staging"), "KB_ASSETS_ROOT": str(tmp_path / "assets"),
        "KM_CONTROL_DB_URL": "sqlite:///" + str(tmp_path / "control.sqlite3"), "KM_SESSION_SIGNING_KEY": "a" * 32,
        "KM_ENTRY_SESSION_SIGNING_KEY": "b" * 32, "KM_CONTROL_SESSION_SIGNING_KEY": "c" * 32, "KM_CONTROL_PUBLIC_ORIGIN": "https://control.example.test",
    }
    for key, value in values.items(): monkeypatch.setenv(key, value)


def _active_user(monkeypatch, tmp_path):
    _instance_env(monkeypatch, tmp_path)
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123")
    pending = registry.register("operator", "strong-password-123")
    registry.set_user_status(admin.user_id, pending.user_id, "active")
    registry.grant(admin.user_id, pending.user_id, "da40", "user")
    return registry, admin, registry.get_user(pending.user_id)


def test_instance_config_requires_control_db(monkeypatch, tmp_path):
    _instance_env(monkeypatch, tmp_path)
    assert InstanceStoreConfig.from_environment().control_db_url.endswith("control.sqlite3")
    monkeypatch.delenv("KM_CONTROL_DB_URL")
    with pytest.raises(InstanceIsolationError): InstanceStoreConfig.from_environment()


def test_redis_keys_cannot_be_cross_instance_prefixed():
    assert redis_key("da40", "result:abc") == "km:da40:result:abc"
    with pytest.raises(InstanceIsolationError): redis_key("da40", "km:test:result:abc")


def test_pending_user_cannot_login_or_select_an_instance(monkeypatch, tmp_path):
    _instance_env(monkeypatch, tmp_path)
    registry = ControlRegistry.from_environment()
    registry.bootstrap_admin("admin", "strong-password-123")
    pending = registry.register("pending", "strong-password-123")
    with pytest.raises(ControlAuthorizationError): registry.authenticate("pending", "strong-password-123")
    with pytest.raises(ControlAuthorizationError): registry.create_login_code(pending, "test")


def test_entry_token_is_bound_to_grant_and_revokes_immediately(monkeypatch, tmp_path):
    registry, admin, user = _active_user(monkeypatch, tmp_path)
    assert user is not None
    token = issue_entry_session(user.user_id, "da40", "user", user.session_epoch)
    assert verify_entry_session(token, "da40")["sub"] == user.user_id
    with pytest.raises(ControlAuthenticationError): verify_entry_session(token, "test")
    registry.set_user_status(admin.user_id, user.user_id, "disabled")
    with pytest.raises(ControlAuthorizationError): registry.validate_entry_claims(user.user_id, "da40", "user", user.session_epoch)


def test_one_time_code_cannot_be_used_for_another_instance_or_twice(monkeypatch, tmp_path):
    registry, _admin, user = _active_user(monkeypatch, tmp_path)
    assert user is not None
    code = registry.create_login_code(user, "da40")
    with pytest.raises(ControlAuthenticationError): registry.consume_login_code(code, "rd2")
    consumed, role = registry.consume_login_code(code, "da40")
    assert consumed.user_id == user.user_id and role == "user"
    with pytest.raises(ControlAuthenticationError): registry.consume_login_code(code, "da40")


def test_control_session_has_no_password_claim(monkeypatch, tmp_path):
    _registry, _admin, user = _active_user(monkeypatch, tmp_path)
    assert user is not None
    assert "strong-password" not in issue_control_session(user)


def test_data_plane_only_allows_health_and_entry_callback_without_session():
    from src.web_api.instance_auth_routes import PUBLIC_PATHS, safe_return_path

    assert PUBLIC_PATHS == {"/health", "/api/auth/callback", "/api/auth/login-url"}
    assert "/api/csit/" not in PUBLIC_PATHS
    assert "/" not in PUBLIC_PATHS
    assert safe_return_path("/upload") == "/upload"
    assert safe_return_path("/admin?next=https://evil.example") == "/chat-v2.html"
    assert safe_return_path("https://evil.example") == "/chat-v2.html"
