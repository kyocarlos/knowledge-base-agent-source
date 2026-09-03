from __future__ import annotations

import logging
import re

from fastapi import APIRouter, HTTPException
from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app


def build_client(*, raise_server_exceptions: bool = True) -> TestClient:
    app = create_app(
        AppSettings(
            service_name="kb-contract-test",
            version="9.8.7",
            environment="test",
            commit="abc123",
        )
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def assert_success_envelope(payload: dict, trace_id: str) -> None:
    assert payload["error"] is None
    assert payload["trace_id"] == trace_id
    assert payload["data"] is not None


def test_health_live_ready_and_version_use_the_v1_envelope():
    with build_client() as client:
        health = client.get("/api/v1/health", headers={"X-Trace-ID": "trace-contract-1"})
        live = client.get("/api/v1/health/live")
        ready = client.get("/api/v1/health/ready")
        version = client.get("/api/v1/version")

    assert health.status_code == live.status_code == ready.status_code == version.status_code == 200
    assert_success_envelope(health.json(), "trace-contract-1")
    assert health.headers["X-Trace-ID"] == "trace-contract-1"
    assert health.json()["data"] == {"status": "ok", "live": True, "ready": True}
    assert live.json()["data"]["ready"] is None
    assert ready.json()["data"]["ready"] is True
    assert version.json()["data"] == {
        "service": "kb-contract-test",
        "version": "9.8.7",
        "environment": "test",
        "commit": "abc123",
        "release_id": None,
        "image_digest": None,
        "build_timestamp": None,
    }


def test_version_exposes_release_metadata_when_configured():
    with build_client() as client:
        app = client.app
        app.state.settings = AppSettings(
            service_name="kb-contract-test",
            version="9.8.7",
            environment="test",
            commit="abc123",
            release_id="wp1-selfread-auth-20260831-r1",
            image_digest="sha256:" + "b" * 64,
            build_timestamp="2026-08-31T15:46:55.251425676+08:00",
        )
        response = client.get("/api/v1/version")

    assert response.status_code == 200
    assert response.json()["data"]["release_id"] == "wp1-selfread-auth-20260831-r1"
    assert response.json()["data"]["image_digest"] == "sha256:" + "b" * 64
    assert response.json()["data"]["build_timestamp"] == "2026-08-31T15:46:55.251425676+08:00"


def test_invalid_trace_header_is_replaced_and_same_id_is_logged(caplog):
    caplog.set_level(logging.INFO, logger="app.core.trace")
    with build_client() as client:
        response = client.get("/api/v1/health", headers={"X-Trace-ID": "not valid / trace"})

    trace_id = response.headers["X-Trace-ID"]
    assert re.fullmatch(r"[0-9a-f]{32}", trace_id)
    assert response.json()["trace_id"] == trace_id
    assert f"trace_id={trace_id}" in caplog.text


def test_unknown_v1_route_returns_stable_error_without_internal_details():
    with build_client() as client:
        response = client.get("/api/v1/does-not-exist", headers={"X-Trace-ID": "trace-404"})

    assert response.status_code == 404
    assert response.headers["X-Trace-ID"] == "trace-404"
    assert response.json() == {
        "data": None,
        "error": {"code": "http_404", "message": "Not Found"},
        "trace_id": "trace-404",
    }


def test_store_consistency_error_preserves_sanitized_details():
    app = create_app(AppSettings(environment="test"))
    test_router = APIRouter(prefix="/api/v1")

    @test_router.get("/_store-failure")
    async def store_failure():
        raise HTTPException(
            status_code=409,
            detail={
                "code": "store_consistency_failure",
                "operation": "publish",
                "store_outcomes": {"qdrant": "success", "neo4j": "failed"},
                "partial_write": True,
                "rollback_complete": True,
                "rollback_outcomes": {"qdrant": "compensated"},
                "internal_secret": "must-not-escape",
            },
        )

    app.include_router(test_router)
    with TestClient(app) as client:
        response = client.get("/api/v1/_store-failure", headers={"X-Trace-ID": "trace-store"})

    assert response.status_code == 409
    assert response.json() == {
        "data": None,
        "error": {
            "code": "store_consistency_failure",
            "message": "Store consistency failure",
            "details": {
                "operation": "publish",
                "store_outcomes": {"qdrant": "success", "neo4j": "failed"},
                "partial_write": True,
                "rollback_complete": True,
                "rollback_outcomes": {"qdrant": "compensated"},
            },
        },
        "trace_id": "trace-store",
    }


def test_v1_validation_error_uses_stable_envelope():
    app = create_app(AppSettings(environment="test"))
    test_router = APIRouter(prefix="/api/v1")

    @test_router.get("/_validated")
    async def validated(limit: int):
        return {"limit": limit}

    app.include_router(test_router)
    with TestClient(app) as client:
        response = client.get("/api/v1/_validated?limit=invalid", headers={"X-Trace-ID": "trace-422"})

    assert response.status_code == 422
    assert response.json() == {
        "data": None,
        "error": {"code": "validation_error", "message": "Request validation failed"},
        "trace_id": "trace-422",
    }


def test_unhandled_exception_does_not_expose_message_path_secret_or_stack(caplog):
    app = create_app(AppSettings(environment="test"))
    test_router = APIRouter(prefix="/api/v1")

    @test_router.get("/_raise")
    async def raise_error():
        raise RuntimeError("secret-token at /private/runtime/path")

    app.include_router(test_router)
    caplog.set_level(logging.ERROR, logger="app.core.exceptions")
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/_raise", headers={"X-Trace-ID": "trace-500"})

    rendered = response.text
    assert response.status_code == 500
    assert response.headers["X-Trace-ID"] == "trace-500"
    assert response.json()["error"] == {"code": "internal_error", "message": "Internal server error"}
    assert "secret-token" not in rendered
    assert "/private/runtime/path" not in rendered
    assert "Traceback" not in rendered
    assert "secret-token" not in caplog.text
    assert "/private/runtime/path" not in caplog.text
    assert "trace_id=trace-500" in caplog.text


def test_openapi_contains_new_and_legacy_contracts():
    with build_client() as client:
        paths = client.get("/openapi.json").json()["paths"]

    assert "/api/v1/health" in paths
    assert "/search" in paths
    assert "/api/agent/v1/reports" in paths
    assert "/api/upload/ingest" in paths
