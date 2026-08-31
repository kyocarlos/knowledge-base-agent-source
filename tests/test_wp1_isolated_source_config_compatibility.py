import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[1]


def _load_helper():
    spec = importlib.util.spec_from_file_location("isolated_config", ROOT / "scripts/provision_wp1_isolated_config.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cleanup_auth_symbol_and_route_are_converged() -> None:
    auth = (ROOT / "src/test_reports/auth.py").read_text(encoding="utf-8")
    route = (ROOT / "src/web_api/e2e_cleanup_routes.py").read_text(encoding="utf-8")
    assert "def authenticate_e2e_cleanup" in auth
    assert "from ..test_reports.auth import authenticate_e2e_cleanup" in route
    tree = ast.parse((ROOT / "src/web_api/__init__.py").read_text(encoding="utf-8"))
    source = ast.unparse(tree)
    assert "e2e_cleanup_router" in source


def test_cleanup_auth_valid_identity_is_accepted() -> None:
    auth = _load_auth()
    token = "isolated-cleanup-token"
    os.environ.update({
        "KB_E2E_CLEANUP_TOKEN_HASHES_JSON": json.dumps({
            "e2e-cleanup-01": {"token_sha256": hashlib.sha256(token.encode()).hexdigest()}
        })
    })
    request = type("Request", (), {"headers": {
        "Authorization": f"Bearer {token}", "X-E2E-Cleanup-ID": "e2e-cleanup-01"
    }})()
    assert auth.authenticate_e2e_cleanup(request)["scope"] == "e2e:cleanup"


@pytest.mark.parametrize("headers", [
    {"Authorization": "Bearer isolated-cleanup-token"},
    {"Authorization": "Bearer wrong", "X-E2E-Cleanup-ID": "e2e-cleanup-01"},
])
def test_cleanup_auth_missing_or_wrong_identity_fails_closed(headers: dict[str, str]) -> None:
    auth = _load_auth()
    token = "isolated-cleanup-token"
    os.environ.update({
        "KB_E2E_CLEANUP_TOKEN_HASHES_JSON": json.dumps({
            "e2e-cleanup-01": {"token_sha256": hashlib.sha256(token.encode()).hexdigest()}
        })
    })
    with pytest.raises(HTTPException) as error:
        auth.authenticate_e2e_cleanup(type("Request", (), {"headers": headers})())
    assert error.value.status_code in {401, 403}


def _load_auth():
    spec = importlib.util.spec_from_file_location("isolated_auth", ROOT / "src/test_reports/auth.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_provision_isolated_config_is_protected_and_reproducible(tmp_path: Path) -> None:
    helper = _load_helper()
    source = tmp_path / "source.yaml"
    source.write_text("protected: value\n", encoding="utf-8")
    isolated = tmp_path / "isolated-config"
    evidence = tmp_path / "evidence.json"
    record = helper.provision(source, isolated, evidence)
    target = isolated / "config.yaml"
    assert target.read_bytes() == source.read_bytes()
    assert oct(target.stat().st_mode & 0o777) == "0o600"
    assert oct(isolated.stat().st_mode & 0o777) == "0o700"
    assert record["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert json.loads(evidence.read_text())["secrets_included"] is False


def test_provision_rejects_production_output(tmp_path: Path) -> None:
    helper = _load_helper()
    source = tmp_path / "source.yaml"
    source.write_text("x: y\n", encoding="utf-8")
    with pytest.raises(ValueError, match="production path"):
        helper.provision(source, Path("/srv/knowledge-base-production-rebaseline-test"), tmp_path / "e.json")
