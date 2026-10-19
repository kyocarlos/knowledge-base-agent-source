import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

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


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(wifi8_routes, "_wifi8_root", lambda: tmp_path)
    monkeypatch.setattr(wifi8_routes, "_account_name", lambda request: "km-clude1")
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        if request.headers.get("x-test-anonymous") != "1":
            request.state.km_identity = {"sub": "u1", "instance_id": "test"}
        return await call_next(request)

    app.include_router(wifi8_routes.router)
    return TestClient(app), tmp_path


def test_the_switch_needs_a_login_and_a_same_origin_header(client):
    http, root = client
    anonymous = {"x-test-anonymous": "1"}
    assert http.get("/api/wifi8/auto-check", headers=anonymous).status_code == 401
    assert http.post("/api/wifi8/auto-check", json={"enabled": False}, headers={**anonymous, "x-km-wifi8-setting": "1"}).status_code == 401
    assert http.post("/api/wifi8/auto-check", json={"enabled": False}).status_code == 403  # no header: a cross-site form cannot do it
    assert not (root / autocheck.SETTINGS_NAME).exists()


def test_any_logged_in_account_can_switch_it_and_the_change_is_recorded(client):
    http, root = client
    assert http.get("/api/wifi8/auto-check").json()["enabled"] is True
    off = http.post("/api/wifi8/auto-check", json={"enabled": False}, headers={"x-km-wifi8-setting": "1"})
    assert off.status_code == 200 and off.json()["enabled"] is False and off.json()["changed_by"] == "km-clude1"
    assert json.loads((root / autocheck.SETTINGS_NAME).read_text())["enabled"] is False
    assert http.get("/api/wifi8/auto-check").json()["enabled"] is False
    on = http.post("/api/wifi8/auto-check", json={"enabled": True}, headers={"x-km-wifi8-setting": "1"})
    assert on.json()["enabled"] is True


@pytest.mark.parametrize("body", [{"enabled": "false"}, {"enabled": 0}, {"enabled": None}, {}, {"enabled": [True]}])
def test_only_a_real_boolean_is_accepted(client, body):
    http, root = client
    assert http.post("/api/wifi8/auto-check", json=body, headers={"x-km-wifi8-setting": "1"}).status_code == 422
    assert not (root / autocheck.SETTINGS_NAME).exists()
