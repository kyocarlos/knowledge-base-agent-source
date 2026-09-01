import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

from run_wp1_production_acceptance import build_connect_request


def test_connect_request_matches_openclaw_params_schema():
    request = build_connect_request(
        {
            "authToken": "token",
            "deviceToken": "device-token",
            "deviceId": "device",
            "publicKeyRaw": "public-key",
            "client": {
                "id": "cli",
                "version": "1.0.0",
                "platform": "linux",
                "mode": "cli",
                "unexpected": "must be removed",
            },
            "locale": "zh-TW",
            "userAgent": "runner",
        },
        ["operator.read"],
        "signature",
        {"ts": 123, "nonce": "nonce"},
    )

    assert set(request) == {"type", "id", "method", "params"}
    assert set(request["params"]) == {
        "minProtocol",
        "maxProtocol",
        "client",
        "role",
        "scopes",
        "auth",
        "device",
    }
    assert "locale" not in request["params"]
    assert "userAgent" not in request["params"]
    assert "unexpected" not in request["params"]["client"]


def test_connect_request_uses_schema_safe_default_client():
    request = build_connect_request(
        {
            "authToken": "token",
            "deviceId": "device",
            "publicKeyRaw": "public-key",
        },
        ["operator.read"],
        "signature",
        {"ts": 123, "nonce": "nonce"},
    )

    assert request["params"]["client"] == {
        "id": "cli",
        "version": "1.0.0",
        "platform": "linux",
        "mode": "cli",
    }


def test_runner_does_not_send_legacy_auth_frame_before_connect():
    source = (Path(__file__).parents[1] / "scripts" / "run_wp1_production_acceptance.py").read_text()

    assert 'json.dumps({"type": "auth"' not in source
