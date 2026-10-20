import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.km_control import ControlRegistry
from src.web_api import wifi8_routes
from src.wifi8 import quality_schedule

HEADER = {"x-km-wifi8-setting": "1"}
URL = "/api/wifi8/quality-schedule"


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Real KM Control registry (sqlite): alice may move the check of the test zone, bob is a plain account of the same zone."""
    monkeypatch.setenv("KM_CONTROL_DB_URL", "sqlite:///" + str(tmp_path / "control.sqlite3"))
    monkeypatch.setattr(wifi8_routes, "_wifi8_root", lambda: tmp_path / "wifi8")
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123")
    users = {name: registry.create_active_with_grant(admin.user_id, name, "strong-password-123", "user", "test").user_id for name in ("alice", "bob")}
    registry.grant_capability(admin.user_id, users["alice"], "test", quality_schedule.CAPABILITY)
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


def test_everyone_logged_in_can_read_it_and_it_defaults_to_the_usual_time(env):
    http, *_ = env
    assert http.get(URL).status_code == 401
    alice, bob = (http.get(URL, headers=as_(n)).json() for n in ("alice", "bob"))
    assert alice["time"] == bob["time"] == "03:30" and alice["timezone"] == "Asia/Taipei"
    assert alice["can_change"] is True and bob["can_change"] is False


def test_an_authorised_account_chooses_the_time_on_a_24_hour_clock_and_it_is_recorded(env):
    http, registry, admin, users, root = env
    saved = http.post(URL, json={"time": "21:30"}, headers={**as_("alice"), **HEADER}).json()
    assert saved["time"] == "21:30" and saved["changed_by"] == "alice" and saved["timezone"] == "Asia/Taipei"
    stored = json.loads((root / quality_schedule.SETTINGS_NAME).read_text())
    assert stored["time"] == "21:30" and stored["timezone"] == "Asia/Taipei"
    assert http.get(URL, headers=as_("bob")).json()["time"] == "21:30"  # everyone sees it
    for edge in ("00:00", "23:59"):
        assert http.post(URL, json={"time": edge}, headers={**as_("alice"), **HEADER}).json()["time"] == edge


@pytest.mark.parametrize("bad", ["24:00", "9:00", "09:60", "12:00 PM", "9am", "", "0900", "09:00:00", 900, ["09:00"], None])
def test_a_time_that_is_not_hh_mm_on_a_24_hour_clock_is_refused_and_nothing_changes(env, bad):
    http, registry, admin, users, root = env
    assert http.post(URL, json={"time": bad}, headers={**as_("alice"), **HEADER}).status_code == 422
    assert http.post(URL, json={}, headers={**as_("alice"), **HEADER}).status_code == 422  # the time is required
    assert not (root / quality_schedule.SETTINGS_NAME).exists()


def test_an_account_without_the_grant_cannot_move_the_check_even_when_calling_the_api_directly(env):
    http, registry, admin, users, root = env
    assert http.post(URL, json={"time": "10:00"}, headers={**as_("bob"), **HEADER}).status_code == 403
    assert not (root / quality_schedule.SETTINGS_NAME).exists()


def test_a_revoked_grant_applies_on_the_next_request_and_leaves_the_time_alone(env):
    http, registry, admin, users, root = env
    assert http.post(URL, json={"time": "05:00"}, headers={**as_("alice"), **HEADER}).status_code == 200
    registry.revoke_capability(admin.user_id, users["alice"], "test", quality_schedule.CAPABILITY)
    assert http.get(URL, headers=as_("alice")).json()["can_change"] is False
    assert http.post(URL, json={"time": "06:00"}, headers={**as_("alice"), **HEADER}).status_code == 403
    assert quality_schedule.read_settings(root)["time"] == "05:00"
    registry.grant_capability(admin.user_id, users["alice"], "test", quality_schedule.CAPABILITY)
    assert http.post(URL, json={"time": "06:00"}, headers={**as_("alice"), **HEADER}).status_code == 200


def test_a_grant_for_another_zone_or_another_capability_does_not_count(env):
    http, registry, admin, users, root = env
    registry.grant(admin.user_id, users["bob"], "da40", "user")
    registry.grant_capability(admin.user_id, users["bob"], "da40", quality_schedule.CAPABILITY)
    registry.grant_capability(admin.user_id, users["bob"], "test", "wifi8_auto_check")
    assert http.get(URL, headers=as_("bob")).json()["can_change"] is False  # test zone: only the auto-check capability there
    assert http.get(URL, headers=as_("bob", **{"x-test-instance": "da40"})).json()["can_change"] is True


def test_needs_the_same_origin_header(env):
    http, *_ , root = env
    assert http.post(URL, json={"time": "10:00"}, headers=as_("alice")).status_code == 403
    assert not (root / quality_schedule.SETTINGS_NAME).exists()


def test_when_the_control_database_cannot_be_read_the_schedule_is_locked(env, monkeypatch):
    http, *_ = env
    monkeypatch.setattr(ControlRegistry, "has_capability", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database down")))
    assert http.get(URL, headers=as_("alice")).json()["can_change"] is False
    assert http.post(URL, json={"time": "10:00"}, headers={**as_("alice"), **HEADER}).status_code == 403


def test_the_timezone_comes_from_the_deployment_and_a_corrupt_file_reads_as_the_default(env, monkeypatch, tmp_path):
    http, *_ = env
    monkeypatch.setenv("KM_WIFI8_QUALITY_TIMEZONE", "UTC")
    assert http.post(URL, json={"time": "08:00"}, headers={**as_("alice"), **HEADER}).json()["timezone"] == "UTC"
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / quality_schedule.SETTINGS_NAME).write_text('{"time": "7pm"}')
    assert quality_schedule.read_settings(tmp_path / "x")["time"] == "03:30"
    (tmp_path / "x" / quality_schedule.SETTINGS_NAME).write_text("{not json")
    assert quality_schedule.read_settings(tmp_path / "x")["time"] == "03:30"
    with pytest.raises(ValueError):
        quality_schedule.write_settings(tmp_path / "x", "someone", "24:01")
