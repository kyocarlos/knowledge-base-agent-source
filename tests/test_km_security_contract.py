from __future__ import annotations

import os
import hashlib
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web_api.report_routes import router


def test_report_filename_rejects_posix_and_windows_paths() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    token = "ci-agent-token"
    env = {
        "KB_AGENT_TOKEN_HASHES_JSON": '{"agent":{"environment":"anritsu","token_sha256":"%s"}}' % hashlib.sha256(token.encode()).hexdigest(),
        "KB_REVIEWER_TOKEN_HASHES_JSON": "{}",
    }
    with patch.dict(os.environ, env):
        for filename in ("../report.xlsx", r"..\report.xlsx"):
            response = client.post(
                "/api/agent/v1/reports",
                headers={"Authorization": f"Bearer {token}", "X-Agent-ID": "agent"},
                files={"file": (filename, b"not-a-report", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            )
            assert response.status_code == 400


def test_ci_workflows_are_km_only_and_read_only() -> None:
    root = Path(__file__).resolve().parents[1]
    for workflow in (root / ".github/workflows/km-v26-ci.yml", root / ".github/workflows/km-v26-release-validation.yml"):
        text = workflow.read_text(encoding="utf-8")
        assert "contents: read" in text
        assert "docker.sock" not in text
        assert "secrets:" not in text
