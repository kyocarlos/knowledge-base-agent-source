import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).parents[1] / "scripts/run_wp1_production_acceptance.py"


def load_runner():
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("wp1_runner_observation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_http_observation_redacts_credentials_and_preserves_server() -> None:
    runner = load_runner()
    response = Mock()
    response.status = 404
    response.headers = {"Server": "nginx/1.31.0", "Content-Type": "application/json", "Set-Cookie": "secret"}
    response.read.return_value = json.dumps({"detail": "missing", "token": "do-not-record"}).encode()
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *args: False
    with patch.object(runner.urllib.request, "urlopen", return_value=response):
        status, _, observation = runner.request_observed(
            "https://127.0.0.1:3030/api/agent/v1/reports?token=secret",
            {"Authorization": "Bearer secret", "X-Trace-ID": "run-1"},
            method="POST",
            body=b"payload",
        )
    assert status == 404
    assert observation["url"] == "https://127.0.0.1:3030/api/agent/v1/reports?<redacted>"
    assert observation["server"] == "nginx/1.31.0"
    assert "Authorization" not in observation["request_headers"]
    assert "Set-Cookie" not in observation["response_headers"]
    assert "do-not-record" not in observation["body"]
    assert observation["body"] == '{"detail":"missing","token":"[REDACTED]"}'
