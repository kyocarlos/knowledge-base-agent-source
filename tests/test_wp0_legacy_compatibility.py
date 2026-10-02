from __future__ import annotations

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app


def test_legacy_health_response_is_unchanged():
    with TestClient(create_app(AppSettings(environment="test"))) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_legacy_report_agent_auth_contract_is_unchanged():
    with TestClient(create_app(AppSettings(environment="test"))) as client:
        response = client.get("/api/agent/v1/health")

    assert response.status_code == 401
    assert response.json() == {"detail": "缺少 X-Agent-ID"}


def test_legacy_business_and_websocket_routes_are_registered_once():
    app = create_app(AppSettings(environment="test"))
    route_paths = [getattr(route, "path", None) for route in app.router.routes]

    for path in ("/search", "/ws", "/api/upload/ingest", "/api/agent/v1/reports"):
        assert route_paths.count(path) == 1


def test_non_v1_unhandled_error_keeps_legacy_server_error_shape():
    app = create_app(AppSettings(environment="test"))
    test_router = APIRouter()

    @test_router.get("/_legacy_raise")
    async def legacy_raise():
        raise RuntimeError("legacy failure")

    app.include_router(test_router)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/_legacy_raise")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
