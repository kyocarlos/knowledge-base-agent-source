from __future__ import annotations

from fastapi.testclient import TestClient

from src.km_control import ControlRegistry


def _env(monkeypatch, tmp_path):
    for key, value in {
        "KM_CONTROL_DB_URL": "sqlite:///" + str(tmp_path / "control-api.sqlite3"),
        "KM_CONTROL_SESSION_SIGNING_KEY": "c" * 32,
        "KM_ENTRY_SESSION_SIGNING_KEY": "b" * 32,
        "KM_TEST_PUBLIC_ORIGIN": "https://km-test.example.test",
        "KM_DA40_PUBLIC_ORIGIN": "https://km-da40.example.test",
        "KM_RD2_PUBLIC_ORIGIN": "https://km-rd2.example.test",
    }.items(): monkeypatch.setenv(key, value)


def test_registration_pending_login_grant_and_opaque_entry_code(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        registered = client.post("/api/auth/register", json={"username": "operator", "password": "strong-password-123"})
        assert registered.status_code == 201
        assert "password" not in registered.text.lower()
        assert client.post("/api/auth/login", json={"username": "operator", "password": "strong-password-123"}).status_code == 403

        registry = ControlRegistry.from_environment()
        admin = registry.bootstrap_admin("admin", "strong-password-123")
        registry.set_user_status(admin.user_id, registered.json()["user_id"], "active")
        registry.grant(admin.user_id, registered.json()["user_id"], "da40", "user")

        assert client.post("/api/auth/login", json={"username": "operator", "password": "strong-password-123"}).status_code == 200
        selected = client.post("/api/auth/select-instance", json={"instance_id": "da40"})
        assert selected.status_code == 200
        assert selected.json()["redirect_url"].startswith("https://km-da40.example.test/api/auth/callback?code=")
        assert "operator" not in selected.json()["redirect_url"]
        selected_with_return = client.post("/api/auth/select-instance?return_to=%2Fupload", json={"instance_id": "da40"})
        assert selected_with_return.status_code == 200
        assert "return_to=%2Fupload" in selected_with_return.json()["redirect_url"]


def test_admin_can_list_grant_and_revoke_without_exposing_passwords(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        registered = client.post("/api/auth/register", json={"username": "operator", "password": "strong-password-123"})
        registry = ControlRegistry.from_environment()
        registry.bootstrap_admin("admin", "strong-password-123")

        admin_login = client.post("/api/auth/login", json={"username": "admin", "password": "strong-password-123"})
        assert admin_login.status_code == 200
        assert admin_login.json()["is_admin"] is True
        users = client.get("/api/auth/admin/users")
        assert users.status_code == 200
        operator = next(item for item in users.json()["users"] if item["user_id"] == registered.json()["user_id"])
        assert "password" not in str(operator).lower()
        assert operator["instances"] == []

        user_id = registered.json()["user_id"]
        assert client.put(f"/api/auth/admin/users/{user_id}/grants/test", json={"role": "user"}).status_code == 200
        assert client.delete(f"/api/auth/admin/users/{user_id}/grants/test").status_code == 200
        assert registry.grants_for(user_id) == []


def test_test_only_configuration_refuses_da40_and_rd2(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("KM_ENABLED_INSTANCE_IDS", "test")
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        registered = client.post("/api/auth/register", json={"username": "operator", "password": "strong-password-123"})
        registry = ControlRegistry.from_environment()
        admin = registry.bootstrap_admin("admin", "strong-password-123")
        registry.set_user_status(admin.user_id, registered.json()["user_id"], "active")
        assert client.post("/api/auth/login", json={"username": "admin", "password": "strong-password-123"}).status_code == 200
        assert client.put(f"/api/auth/admin/users/{registered.json()['user_id']}/grants/da40", json={"role": "user"}).status_code == 422
        assert client.put(f"/api/auth/admin/users/{registered.json()['user_id']}/grants/test", json={"role": "user"}).status_code == 200
        assert client.get("/api/auth/admin/users").json()["enabled_instances"] == ["test"]


def test_admin_can_create_active_test_only_account_without_password_leak(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("KM_ENABLED_INSTANCE_IDS", "test")
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        registry = ControlRegistry.from_environment()
        admin = registry.bootstrap_admin("admin", "strong-password-123")
        assert client.post("/api/auth/login", json={"username": "admin", "password": "strong-password-123"}).status_code == 200
        created = client.post("/api/auth/admin/users", json={"username": "test-reader", "password": "reader-password-123", "role": "user"})
        assert created.status_code == 201
        payload = created.json()
        assert payload["status"] == "active"
        assert payload["instances"] == [{"instance_id": "test", "role": "user"}]
        assert "reader-password-123" not in created.text
        assert registry.grants_for(payload["user_id"]) == [{"instance_id": "test", "role": "user"}]
        assert client.post("/api/auth/login", json={"username": "test-reader", "password": "reader-password-123"}).status_code == 200


def test_non_admin_cannot_create_account(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("KM_ENABLED_INSTANCE_IDS", "test")
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        registered = client.post("/api/auth/register", json={"username": "operator", "password": "strong-password-123"})
        registry = ControlRegistry.from_environment()
        admin = registry.bootstrap_admin("admin", "strong-password-123")
        registry.set_user_status(admin.user_id, registered.json()["user_id"], "active")
        assert client.post("/api/auth/login", json={"username": "operator", "password": "strong-password-123"}).status_code == 200
        assert client.post("/api/auth/admin/users", json={"username": "blocked", "password": "blocked-password-123", "role": "user"}).status_code == 403


def test_admin_create_rejects_duplicate_username(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("KM_ENABLED_INSTANCE_IDS", "test")
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        registry = ControlRegistry.from_environment()
        registry.bootstrap_admin("admin", "strong-password-123")
        assert client.post("/api/auth/login", json={"username": "admin", "password": "strong-password-123"}).status_code == 200
        body = {"username": "duplicate", "password": "duplicate-password-123", "role": "user"}
        assert client.post("/api/auth/admin/users", json=body).status_code == 201
        assert client.post("/api/auth/admin/users", json=body).status_code == 422


def test_admin_delete_disables_account_revokes_grants_and_invalidates_self_delete(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("KM_ENABLED_INSTANCE_IDS", "test")
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        registry = ControlRegistry.from_environment()
        admin = registry.bootstrap_admin("admin", "strong-password-123")
        target = registry.create_active_with_grant(admin.user_id, "target", "target-password-123", "user", "test")
        assert client.post("/api/auth/login", json={"username": "admin", "password": "strong-password-123"}).status_code == 200

        deleted = client.delete(f"/api/auth/admin/users/{target.user_id}")
        assert deleted.status_code == 200
        assert deleted.json() == {"user_id": target.user_id, "status": "disabled", "instances": []}
        assert registry.get_user(target.user_id).status == "disabled"
        assert registry.grants_for(target.user_id) == []
        assert client.post("/api/auth/login", json={"username": "target", "password": "target-password-123"}).status_code == 403

        assert client.delete(f"/api/auth/admin/users/{admin.user_id}").status_code == 422


def test_admin_permanently_deletes_only_disabled_account_and_keeps_audit(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("KM_ENABLED_INSTANCE_IDS", "test")
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        registry = ControlRegistry.from_environment()
        admin = registry.bootstrap_admin("admin", "strong-password-123")
        target = registry.create_active_with_grant(admin.user_id, "target", "target-password-123", "user", "test")
        assert client.post("/api/auth/login", json={"username": "admin", "password": "strong-password-123"}).status_code == 200
        assert client.delete(f"/api/auth/admin/users/{target.user_id}/permanent").status_code == 422
        assert client.delete(f"/api/auth/admin/users/{target.user_id}").status_code == 200
        deleted = client.delete(f"/api/auth/admin/users/{target.user_id}/permanent")
        assert deleted.status_code == 200
        assert registry.get_user(target.user_id) is None
        assert registry.grants_for(target.user_id) == []
        with registry._connection() as connection:
            events = connection.execute(registry._sql("SELECT event_type FROM km_audit_events WHERE target_user_id = ?"), (target.user_id,)).fetchall()
        assert "user_permanently_deleted" in {event["event_type"] for event in events}
        assert client.delete(f"/api/auth/admin/users/{admin.user_id}/permanent").status_code == 422


def _capability_setup(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123")
    ids = {}
    for name in ("alice", "bob"):
        user = registry.create_active_with_grant(admin.user_id, name, "strong-password-123", "user", "test")
        ids[name] = user.user_id
    return registry, admin, ids


def test_admin_grants_and_revokes_a_capability_without_logging_the_account_out(monkeypatch, tmp_path):
    registry, admin, ids = _capability_setup(monkeypatch, tmp_path)
    from app.control_main import app
    epoch = registry.get_user(ids["alice"]).session_epoch
    with TestClient(app, base_url="https://control.example.test") as client:
        assert client.post("/api/auth/login", json={"username": "admin", "password": "strong-password-123"}).status_code == 200
        listed = client.get("/api/auth/admin/users").json()
        assert [c["id"] for c in listed["capability_catalog"]] == ["wifi8_summary_notify", "wifi8_auto_check"]
        assert registry.has_capability(ids["alice"], "test", "wifi8_summary_notify") is False
        path = f"/api/auth/admin/users/{ids['alice']}/capabilities/test/wifi8_summary_notify"
        assert client.put(path).status_code == 200
        assert registry.has_capability(ids["alice"], "test", "wifi8_summary_notify") is True
        assert registry.has_capability(ids["bob"], "test", "wifi8_summary_notify") is False
        assert registry.get_user(ids["alice"]).session_epoch == epoch
        users = {u["username"]: u for u in client.get("/api/auth/admin/users").json()["users"]}
        assert users["alice"]["capabilities"] == [{"instance_id": "test", "capability": "wifi8_summary_notify"}] and users["bob"]["capabilities"] == []
        assert client.delete(path).status_code == 200
        assert registry.has_capability(ids["alice"], "test", "wifi8_summary_notify") is False
        assert client.delete(path).status_code == 422  # nothing active to revoke
    with registry._connection() as connection:
        rows = connection.execute("SELECT event_type, actor_user_id, target_user_id, detail_json FROM km_audit_events WHERE event_type LIKE 'capability_%' ORDER BY occurred_at, event_type").fetchall()
    assert sorted(r["event_type"] for r in rows) == ["capability_granted", "capability_revoked"]
    assert all(r["actor_user_id"] == admin.user_id and r["target_user_id"] == ids["alice"] and "wifi8_summary_notify" in r["detail_json"] for r in rows)


def test_only_a_control_admin_can_change_capabilities_and_inputs_are_validated(monkeypatch, tmp_path):
    registry, admin, ids = _capability_setup(monkeypatch, tmp_path)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as client:
        assert client.post("/api/auth/login", json={"username": "alice", "password": "strong-password-123"}).status_code == 200
        own = f"/api/auth/admin/users/{ids['alice']}/capabilities/test/wifi8_summary_notify"
        assert client.put(own).status_code == 403  # an account cannot grant itself
        assert client.delete(own).status_code == 403
    with TestClient(app, base_url="https://control.example.test") as client:
        assert client.post("/api/auth/login", json={"username": "admin", "password": "strong-password-123"}).status_code == 200
        base = f"/api/auth/admin/users/{ids['alice']}/capabilities"
        assert client.put(f"{base}/test/not_a_capability").status_code == 422
        assert client.put(f"{base}/rd2/wifi8_summary_notify").status_code == 422  # instance not enabled / not offered for it
        assert client.put(f"/api/auth/admin/users/{ids['alice']}/capabilities/da40/wifi8_summary_notify").status_code == 422  # no grant for da40
        assert registry.has_capability(ids["alice"], "test", "wifi8_summary_notify") is False


def test_a_capability_stops_working_when_the_account_or_its_instance_grant_goes_away(monkeypatch, tmp_path):
    registry, admin, ids = _capability_setup(monkeypatch, tmp_path)
    registry.grant_capability(admin.user_id, ids["alice"], "test", "wifi8_summary_notify")
    registry.grant_capability(admin.user_id, ids["bob"], "test", "wifi8_summary_notify")
    assert registry.has_capability(ids["alice"], "test", "wifi8_summary_notify")
    registry.revoke_grant(admin.user_id, ids["alice"], "test")
    assert registry.has_capability(ids["alice"], "test", "wifi8_summary_notify") is False  # lost the zone
    registry.delete_user(admin.user_id, ids["bob"])
    assert registry.has_capability(ids["bob"], "test", "wifi8_summary_notify") is False  # disabled account
    registry.grant(admin.user_id, ids["alice"], "test", "user")
    assert registry.has_capability(ids["alice"], "test", "wifi8_summary_notify") is True  # same zone again, the grant record is still there
    registry.permanently_delete_user(admin.user_id, ids["bob"])
    assert registry.capabilities_for(ids["bob"]) == []


def test_capability_checks_fail_closed_when_the_store_or_catalog_is_unavailable(monkeypatch, tmp_path):
    registry, admin, ids = _capability_setup(monkeypatch, tmp_path)
    registry.grant_capability(admin.user_id, ids["alice"], "test", "wifi8_summary_notify")
    with registry._connection() as connection:
        connection.execute("DROP TABLE km_capability_grants")
    assert registry.has_capability(ids["alice"], "test", "wifi8_summary_notify") is False
    assert registry.capabilities_for(ids["alice"]) == []
    import pytest
    from src.km_control import ControlError
    with pytest.raises(ControlError):
        registry.grant_capability(admin.user_id, ids["alice"], "test", "wifi8_summary_notify")
    monkeypatch.setenv("KM_CAPABILITIES_FILE", str(tmp_path / "missing.json"))
    with pytest.raises(ControlError):
        registry.grant_capability(admin.user_id, ids["alice"], "test", "wifi8_summary_notify")
