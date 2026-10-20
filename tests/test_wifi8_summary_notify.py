import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.km_control import ControlRegistry
from src.web_api import wifi8_routes
from src.wifi8 import summary_notify

HEADER = {"x-km-wifi8-setting": "1"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Real KM Control registry (sqlite): alice is authorised for the switch, bob is a plain account of the same zone."""
    monkeypatch.setenv("KM_CONTROL_DB_URL", "sqlite:///" + str(tmp_path / "control.sqlite3"))
    monkeypatch.setattr(wifi8_routes, "_wifi8_root", lambda: tmp_path / "wifi8")
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123")
    users = {name: registry.create_active_with_grant(admin.user_id, name, "strong-password-123", "user", "test").user_id for name in ("alice", "bob")}
    registry.grant_capability(admin.user_id, users["alice"], "test", summary_notify.CAPABILITY)
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        who = request.headers.get("x-test-user")
        if who:
            request.state.km_identity = {"sub": users.get(who, who), "instance_id": request.headers.get("x-test-instance", "test")}
        return await call_next(request)

    app.include_router(wifi8_routes.router)
    return TestClient(app), registry, admin, users, tmp_path / "wifi8"


def as_(name, **extra):
    return {"x-test-user": name, **extra}


def test_everyone_logged_in_can_read_it_and_it_defaults_to_off(env):
    http, *_ = env
    assert http.get("/api/wifi8/summary-notify").status_code == 401
    alice, bob = (http.get("/api/wifi8/summary-notify", headers=as_(n)).json() for n in ("alice", "bob"))
    assert alice["enabled"] is False and alice["can_change"] is True
    assert bob["enabled"] is False and bob["can_change"] is False


def test_an_authorised_account_switches_it_and_the_change_is_recorded(env):
    http, registry, admin, users, root = env
    on = http.post("/api/wifi8/summary-notify", json={"enabled": True}, headers={**as_("alice"), **HEADER})
    assert on.status_code == 200 and on.json()["enabled"] is True and on.json()["changed_by"] == "alice"
    assert json.loads((root / summary_notify.SETTINGS_NAME).read_text())["enabled"] is True
    assert http.get("/api/wifi8/summary-notify", headers=as_("bob")).json()["enabled"] is True  # everyone sees the state
    off = http.post("/api/wifi8/summary-notify", json={"enabled": False}, headers={**as_("alice"), **HEADER})
    assert off.json()["enabled"] is False


def test_an_account_without_the_grant_cannot_change_it_even_when_calling_the_api_directly(env):
    http, registry, admin, users, root = env
    refused = http.post("/api/wifi8/summary-notify", json={"enabled": True}, headers={**as_("bob"), **HEADER})
    assert refused.status_code == 403
    assert not (root / summary_notify.SETTINGS_NAME).exists()


def test_a_revoked_grant_applies_on_the_next_request(env):
    http, registry, admin, users, root = env
    assert http.post("/api/wifi8/summary-notify", json={"enabled": True}, headers={**as_("alice"), **HEADER}).status_code == 200
    registry.revoke_capability(admin.user_id, users["alice"], "test", summary_notify.CAPABILITY)
    assert http.get("/api/wifi8/summary-notify", headers=as_("alice")).json()["can_change"] is False
    assert http.post("/api/wifi8/summary-notify", json={"enabled": False}, headers={**as_("alice"), **HEADER}).status_code == 403
    assert summary_notify.read_settings(root)["enabled"] is True  # the state stays as it was
    registry.grant_capability(admin.user_id, users["alice"], "test", summary_notify.CAPABILITY)
    assert http.post("/api/wifi8/summary-notify", json={"enabled": False}, headers={**as_("alice"), **HEADER}).status_code == 200


def test_a_grant_for_another_zone_does_not_count(env):
    http, registry, admin, users, root = env
    registry.grant(admin.user_id, users["bob"], "da40", "user")
    registry.grant_capability(admin.user_id, users["bob"], "da40", summary_notify.CAPABILITY)
    # bob holds the capability for da40 only; the same account in the test zone is still locked
    assert http.get("/api/wifi8/summary-notify", headers=as_("bob")).json()["can_change"] is False
    assert http.get("/api/wifi8/summary-notify", headers=as_("bob", **{"x-test-instance": "da40"})).json()["can_change"] is True


def test_needs_the_same_origin_header_and_a_real_boolean(env):
    http, *_ , root = env
    assert http.post("/api/wifi8/summary-notify", json={"enabled": True}, headers=as_("alice")).status_code == 403
    assert http.post("/api/wifi8/summary-notify", json={"enabled": "true"}, headers={**as_("alice"), **HEADER}).status_code == 422
    assert not (root / summary_notify.SETTINGS_NAME).exists()


def test_when_the_control_database_cannot_be_read_the_switch_is_locked(env, monkeypatch):
    http, *_ = env
    monkeypatch.setattr(ControlRegistry, "has_capability", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database down")))
    assert http.get("/api/wifi8/summary-notify", headers=as_("alice")).json()["can_change"] is False
    assert http.post("/api/wifi8/summary-notify", json={"enabled": True}, headers={**as_("alice"), **HEADER}).status_code == 403


def test_a_corrupt_or_missing_file_means_off(tmp_path):
    assert summary_notify.read_settings(tmp_path)["enabled"] is False
    (tmp_path / summary_notify.SETTINGS_NAME).write_text("{not json")
    assert summary_notify.read_settings(tmp_path)["enabled"] is False
    (tmp_path / summary_notify.SETTINGS_NAME).write_text('{"enabled": "yes"}')
    assert summary_notify.read_settings(tmp_path)["enabled"] is False  # only a real true turns it on


def test_the_time_defaults_to_nine_and_is_chosen_on_a_24_hour_clock(env):
    http, registry, admin, users, root = env
    assert http.get("/api/wifi8/summary-notify", headers=as_("bob")).json()["time"] == "09:00"
    saved = http.post("/api/wifi8/summary-notify", json={"enabled": True, "time": "21:30"}, headers={**as_("alice"), **HEADER}).json()
    assert saved["enabled"] is True and saved["time"] == "21:30" and saved["timezone"] == "Asia/Taipei"
    stored = json.loads((root / summary_notify.SETTINGS_NAME).read_text())
    assert stored["time"] == "21:30" and stored["timezone"] == "Asia/Taipei"
    assert http.get("/api/wifi8/summary-notify", headers=as_("bob")).json()["time"] == "21:30"  # everyone sees it
    for edge in ("00:00", "23:59"):
        assert http.post("/api/wifi8/summary-notify", json={"enabled": True, "time": edge}, headers={**as_("alice"), **HEADER}).json()["time"] == edge


def test_switching_without_a_time_keeps_the_chosen_time(env):
    http, *_ = env
    http.post("/api/wifi8/summary-notify", json={"enabled": True, "time": "06:15"}, headers={**as_("alice"), **HEADER})
    off = http.post("/api/wifi8/summary-notify", json={"enabled": False}, headers={**as_("alice"), **HEADER}).json()
    assert off["enabled"] is False and off["time"] == "06:15"


@pytest.mark.parametrize("bad", ["24:00", "9:00", "09:60", "12:00 PM", "9am", "", "0900", "09:00:00", 900, ["09:00"]])
def test_a_time_that_is_not_hh_mm_on_a_24_hour_clock_is_refused_and_nothing_changes(env, bad):
    http, registry, admin, users, root = env
    refused = http.post("/api/wifi8/summary-notify", json={"enabled": True, "time": bad}, headers={**as_("alice"), **HEADER})
    assert refused.status_code == 422
    assert not (root / summary_notify.SETTINGS_NAME).exists()


def test_a_user_without_the_grant_cannot_change_the_time_either(env):
    http, registry, admin, users, root = env
    assert http.post("/api/wifi8/summary-notify", json={"enabled": True, "time": "10:00"}, headers={**as_("bob"), **HEADER}).status_code == 403
    assert not (root / summary_notify.SETTINGS_NAME).exists()


def test_the_timezone_comes_from_the_deployment_and_a_corrupt_time_reads_as_the_default(env, monkeypatch, tmp_path):
    http, registry, admin, users, root = env
    monkeypatch.setenv("KM_WIFI8_SUMMARY_TIMEZONE", "UTC")
    assert http.post("/api/wifi8/summary-notify", json={"enabled": True, "time": "08:00"}, headers={**as_("alice"), **HEADER}).json()["timezone"] == "UTC"
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / summary_notify.SETTINGS_NAME).write_text('{"enabled": true, "time": "7pm"}')
    assert summary_notify.read_settings(tmp_path / "x")["time"] == "09:00"
    with pytest.raises(ValueError):
        summary_notify.write_settings(tmp_path / "x", True, "someone", "24:01")
