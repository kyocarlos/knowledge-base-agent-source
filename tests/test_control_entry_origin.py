"""select-instance keeps the data-plane callback on the site the user signed in from."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.km_control import ControlRegistry

DEV = "https://km-dev.example.test:3030"
IP = "https://203.0.113.9:3030"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    for key, value in {
        "KM_CONTROL_DB_URL": "sqlite:///" + str(tmp_path / "control.sqlite3"),
        "KM_CONTROL_SESSION_SIGNING_KEY": "c" * 32,
        "KM_ENTRY_SESSION_SIGNING_KEY": "b" * 32,
        "KM_ENABLED_INSTANCE_IDS": "test,da40,rd2",
        "KM_TEST_PUBLIC_ORIGIN": DEV,
        "KM_DA40_PUBLIC_ORIGIN": DEV + "/da40",
        "KM_RD2_PUBLIC_ORIGIN": DEV + "/rd2",
        "KM_TEST_PUBLIC_ORIGIN_ALIASES": IP,
        "KM_DA40_PUBLIC_ORIGIN_ALIASES": f" {IP} , https://other.example.test:3030 ",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("KM_RD2_PUBLIC_ORIGIN_ALIASES", raising=False)
    from app.control_main import app
    with TestClient(app, base_url="https://control.example.test") as test_client:
        registry = ControlRegistry.from_environment()
        admin = registry.bootstrap_admin("admin", "strong-password-123")
        user = registry.create_active_with_grant(admin.user_id, "operator", "strong-password-123", "user", "test")
        registry.grant(admin.user_id, user.user_id, "da40", "user")
        registry.grant(admin.user_id, user.user_id, "rd2", "user")
        assert test_client.post("/api/auth/login", json={"username": "operator", "password": "strong-password-123"}).status_code == 200
        yield test_client


def _redirect(client, instance_id, origin=None):
    headers = {"origin": origin} if origin is not None else {}
    response = client.post("/api/auth/select-instance?return_to=%2Fchat-v2.html", json={"instance_id": instance_id}, headers=headers)
    assert response.status_code == 200
    return response.json()["redirect_url"]


@pytest.mark.parametrize("instance_id,expected", [("test", IP + "/api/auth/callback?"), ("da40", IP + "/da40/api/auth/callback?")])
def test_allowed_alias_keeps_callback_on_sign_in_site(client, instance_id, expected):
    assert _redirect(client, instance_id, IP).startswith(expected)


def test_configured_origin_still_matches_itself(client):
    assert _redirect(client, "da40", DEV).startswith(DEV + "/da40/api/auth/callback?")


@pytest.mark.parametrize("origin", [None, "", "null", "https://evil.example.test:3030", "http://203.0.113.9:3030",
                                    "https://203.0.113.9:3031", IP + "/da40", "https://203.0.113.9:3030@evil.example.test"])
def test_unlisted_or_malformed_origin_falls_back_to_configured(client, origin):
    assert _redirect(client, "test", origin).startswith(DEV + "/api/auth/callback?")


def test_instance_without_aliases_is_unchanged(client):
    assert _redirect(client, "rd2", IP).startswith(DEV + "/rd2/api/auth/callback?")


def test_return_path_and_code_are_preserved(client):
    url = _redirect(client, "test", IP)
    assert "return_to=%2Fchat-v2.html" in url and "code=" in url and "operator" not in url
