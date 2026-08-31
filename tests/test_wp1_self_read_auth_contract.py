import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
VALID_TOKEN = "isolated" + "-agent-token"
WRONG_TOKEN = "wrong"
AUTH_SPEC = importlib.util.spec_from_file_location("wp1_auth", ROOT / "src/test_reports/auth.py")
AUTH_MODULE = importlib.util.module_from_spec(AUTH_SPEC)
assert AUTH_SPEC.loader is not None
AUTH_SPEC.loader.exec_module(AUTH_MODULE)
authenticate_report_agent = AUTH_MODULE.authenticate_report_agent


def request(headers: dict[str, str]) -> SimpleNamespace:
    return SimpleNamespace(headers=headers)


def test_self_read_route_uses_e2e_aware_agent_authenticator() -> None:
    tree = ast.parse((ROOT / "src/web_api/report_routes.py").read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_agent_report")
    calls = {node.func.id for node in ast.walk(function) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "authenticate_report_agent" in calls
    assert "authenticate_agent" not in calls


def test_runner_self_read_sends_e2e_headers() -> None:
    source = (ROOT / "scripts/run_wp1_production_acceptance.py").read_text(encoding="utf-8")
    section = source[source.index("self_read_status"):source.index("evidence[\"self_read\"]")]
    assert '"X-E2E-Agent-ID"' in section
    assert '"X-E2E-Test-Mode"' in section
    assert '"X-E2E-Test-Run-ID"' in section


def test_valid_e2e_identity_is_accepted() -> None:
    token = VALID_TOKEN
    env = {
        "KB_E2E_WRITE_MODE_ENABLED": "true",
        "KB_E2E_AGENT_TOKEN_HASHES_JSON": json.dumps({
            "e2e-agent-01": {
                "environment": "anritsu",
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            }
        }),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-E2E-Agent-ID": "e2e-agent-01",
        "X-E2E-Test-Mode": "true",
    }
    with patch.dict(os.environ, env, clear=False):
        assert authenticate_report_agent(request(headers))["agent_id"] == "e2e-agent-01"


@pytest.mark.parametrize("headers", [
    {"Authorization": "Bearer " + VALID_TOKEN, "X-E2E-Test-Mode": "true"},
    {"Authorization": "Bearer " + WRONG_TOKEN, "X-E2E-Agent-ID": "e2e-agent-01", "X-E2E-Test-Mode": "true"},
])
def test_missing_or_wrong_e2e_identity_fails_closed(headers: dict[str, str]) -> None:
    token = VALID_TOKEN
    env = {
        "KB_E2E_WRITE_MODE_ENABLED": "true",
        "KB_E2E_AGENT_TOKEN_HASHES_JSON": json.dumps({
            "e2e-agent-01": {"environment": "anritsu", "token_sha256": hashlib.sha256(token.encode()).hexdigest()}
        }),
    }
    with patch.dict(os.environ, env, clear=False):
        with pytest.raises(HTTPException) as error:
            authenticate_report_agent(request(headers))
    assert error.value.status_code in {401, 403}


def test_e2e_mode_disabled_fails_closed() -> None:
    with patch.dict(os.environ, {"KB_E2E_WRITE_MODE_ENABLED": "false"}, clear=False):
        with pytest.raises(HTTPException) as error:
            authenticate_report_agent(request({
                "Authorization": "Bearer " + VALID_TOKEN,
                "X-E2E-Agent-ID": "e2e-agent-01",
                "X-E2E-Test-Mode": "true",
            }))
    assert error.value.status_code == 404
