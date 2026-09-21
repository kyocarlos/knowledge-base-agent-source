from __future__ import annotations

import hashlib
import json
import os
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web_api.timeseries_routes import router


class _FakeStore:
    def list_runs(self, project: str, limit: int = 50):
        return [{"run_id": "RUN-1", "project_code": project, "document_version": "r1"}]


def test_report_timeseries_requires_existing_reviewer_bearer_and_scope() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    token = "ci-report-reader"
    env = {"KB_REVIEWER_TOKEN_HASHES_JSON": json.dumps({"ci": {"token_sha256": hashlib.sha256(token.encode()).hexdigest()}})}
    with patch.dict(os.environ, env), patch("src.web_api.timeseries_routes._store", return_value=_FakeStore()):
        missing = client.get("/api/v1/reports/timeseries/runs", headers={"X-KM-Project": "KM-CI", "X-KM-Role": "report-reader"})
        assert missing.status_code == 401

        invalid = client.get("/api/v1/reports/timeseries/runs", headers={"Authorization": "Bearer wrong", "X-KM-Project": "KM-CI", "X-KM-Role": "report-reader"})
        assert invalid.status_code == 403

        valid = client.get("/api/v1/reports/timeseries/runs", headers={"Authorization": f"Bearer {token}", "X-KM-Project": "KM-CI", "X-KM-Role": "report-reader"})
        assert valid.status_code == 200
        assert valid.json()["items"][0]["project_code"] == "KM-CI"
