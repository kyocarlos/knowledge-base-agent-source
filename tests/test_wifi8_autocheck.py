import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.km_control import ControlRegistry
from src.web_api import wifi8_routes
from src.wifi8 import autocheck

NOW = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)


def test_no_settings_file_means_on_and_a_corrupt_one_does_too(tmp_path):
    assert autocheck.read_settings(tmp_path)["enabled"] is True
    (tmp_path / autocheck.SETTINGS_NAME).write_text("{not json")
    assert autocheck.read_settings(tmp_path) == {"enabled": True, "changed_by": None, "changed_at": None}


def test_switching_off_and_on_is_remembered_with_who_did_it(tmp_path):
    autocheck.write_settings(tmp_path / "wifi8", False, "km-clude1")
    settings = autocheck.read_settings(tmp_path / "wifi8")
    assert settings["enabled"] is False and settings["changed_by"] == "km-clude1" and settings["changed_at"]
    autocheck.write_settings(tmp_path / "wifi8", True, "someone-else")
    assert autocheck.read_settings(tmp_path / "wifi8")["enabled"] is True
    assert not list((tmp_path / "wifi8").glob("tmp*"))  # the atomic write leaves nothing behind


def test_view_reports_a_watcher_that_stopped_reporting(tmp_path):
    assert autocheck.view(tmp_path, NOW)["watcher_overdue"] is True  # it never reported
    status = {"last_poll_at": (NOW - timedelta(minutes=4)).isoformat(), "interval_minutes": 5,
              "watching": {"package_id": "p"}, "last_check": {"status": "PASS"}}
    (tmp_path / autocheck.STATUS_NAME).write_text(json.dumps(status))
    view = autocheck.view(tmp_path, NOW)
    assert view["watcher_overdue"] is False and view["watching"] == {"package_id": "p"} and view["last_check"] == {"status": "PASS"} and view["enabled"] is True
    status["last_poll_at"] = (NOW - timedelta(minutes=16)).isoformat()  # more than three intervals
    (tmp_path / autocheck.STATUS_NAME).write_text(json.dumps(status))
    assert autocheck.view(tmp_path, NOW)["watcher_overdue"] is True


HEADER = {"x-km-wifi8-setting": "1"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Real KM Control registry (sqlite): alice holds the auto-check capability for the test zone, bob is a plain account of it."""
    monkeypatch.setenv("KM_CONTROL_DB_URL", "sqlite:///" + str(tmp_path / "control.sqlite3"))
    monkeypatch.setattr(wifi8_routes, "_wifi8_root", lambda: tmp_path / "wifi8")
    monkeypatch.setattr(wifi8_routes, "_account_name", lambda request: request.state.km_identity["name"])
    registry = ControlRegistry.from_environment()
    admin = registry.bootstrap_admin("admin", "strong-password-123")
    users = {n: registry.create_active_with_grant(admin.user_id, n, "strong-password-123", "user", "test").user_id for n in ("alice", "bob")}
    registry.grant_capability(admin.user_id, users["alice"], "test", autocheck.CAPABILITY)
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        who = request.headers.get("x-test-user")
        if who:
            request.state.km_identity = {"sub": users[who], "instance_id": "test", "name": who}
        return await call_next(request)

    app.include_router(wifi8_routes.router)
    return TestClient(app), tmp_path / "wifi8", registry, admin, users


def as_(name):
    return {"x-test-user": name}


def test_the_switch_needs_a_login_and_a_same_origin_header(client):
    http, root, *_ = client
    assert http.get("/api/wifi8/auto-check").status_code == 401
    assert http.post("/api/wifi8/auto-check", json={"enabled": False}, headers=HEADER).status_code == 401
    assert http.post("/api/wifi8/auto-check", json={"enabled": False}, headers=as_("alice")).status_code == 403  # no header: a cross-site form cannot do it
    assert not (root / autocheck.SETTINGS_NAME).exists()


def test_everyone_can_read_it_and_only_an_authorised_account_can_switch_it(client):
    http, root, *_ = client
    alice, bob = (http.get("/api/wifi8/auto-check", headers=as_(n)).json() for n in ("alice", "bob"))
    assert alice["enabled"] is True and alice["can_change"] is True and bob["enabled"] is True and bob["can_change"] is False
    refused = http.post("/api/wifi8/auto-check", json={"enabled": False}, headers={**as_("bob"), **HEADER})
    assert refused.status_code == 403 and not (root / autocheck.SETTINGS_NAME).exists()
    off = http.post("/api/wifi8/auto-check", json={"enabled": False}, headers={**as_("alice"), **HEADER})
    assert off.status_code == 200 and off.json()["enabled"] is False and off.json()["changed_by"] == "alice" and off.json()["can_change"] is True
    assert json.loads((root / autocheck.SETTINGS_NAME).read_text())["enabled"] is False
    assert http.get("/api/wifi8/auto-check", headers=as_("bob")).json()["enabled"] is False  # everyone sees the state
    assert http.post("/api/wifi8/auto-check", json={"enabled": True}, headers={**as_("alice"), **HEADER}).json()["enabled"] is True


def test_the_settings_are_authorised_separately(client):
    http, root, registry, admin, users = client
    registry.grant_capability(admin.user_id, users["bob"], "test", "wifi8_quality_schedule")
    assert http.get("/api/wifi8/quality-schedule", headers=as_("bob")).json()["can_change"] is True
    assert http.get("/api/wifi8/auto-check", headers=as_("bob")).json()["can_change"] is False  # the other capability does not carry over
    assert http.get("/api/wifi8/quality-schedule", headers=as_("alice")).json()["can_change"] is False
    assert http.post("/api/wifi8/auto-check", json={"enabled": False}, headers={**as_("bob"), **HEADER}).status_code == 403


def test_a_revoked_grant_applies_on_the_next_request_and_leaves_the_state_alone(client):
    http, root, registry, admin, users = client
    assert http.post("/api/wifi8/auto-check", json={"enabled": False}, headers={**as_("alice"), **HEADER}).status_code == 200
    registry.revoke_capability(admin.user_id, users["alice"], "test", autocheck.CAPABILITY)
    assert http.get("/api/wifi8/auto-check", headers=as_("alice")).json()["can_change"] is False
    assert http.post("/api/wifi8/auto-check", json={"enabled": True}, headers={**as_("alice"), **HEADER}).status_code == 403
    assert autocheck.read_settings(root)["enabled"] is False


def test_when_the_control_database_cannot_be_read_the_switch_is_locked(client, monkeypatch):
    http, *_ = client
    monkeypatch.setattr(ControlRegistry, "has_capability", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("database down")))
    assert http.get("/api/wifi8/auto-check", headers=as_("alice")).json()["can_change"] is False
    assert http.post("/api/wifi8/auto-check", json={"enabled": False}, headers={**as_("alice"), **HEADER}).status_code == 403


@pytest.mark.parametrize("body", [{"enabled": "false"}, {"enabled": 0}, {"enabled": None}, {}, {"enabled": [True]}])
def test_only_a_real_boolean_is_accepted(client, body):
    http, root, *_ = client
    assert http.post("/api/wifi8/auto-check", json=body, headers={**as_("alice"), **HEADER}).status_code == 422
    assert not (root / autocheck.SETTINGS_NAME).exists()
