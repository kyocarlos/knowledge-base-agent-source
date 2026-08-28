from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/diagnose_openclaw_websocket_protocol.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openclaw_ws_protocol", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_and_invalid_tokens_fail_closed_before_chat() -> None:
    module = load_module()
    for name, token in (("empty", ""), ("invalid", "wrong"), ("removed", None)):
        result = module.run_case(name, token)
        assert result["auth_result"] == "FAIL_CLOSED"
        assert result["ready_ack"] is False
        assert result["chat_send_allowed"] is False
        assert result["chat_send_sent"] is False
        assert result["close_code"] == 4401


def test_valid_identity_requires_ready_then_receives_final_event() -> None:
    module = load_module()
    result = module.run_case("valid", module.EXPECTED_TOKEN)
    assert result["auth_result"] == "PASS"
    assert result["ready_ack"] is True
    assert result["chat_send_allowed"] is True
    assert result["chat_send_sent"] is True
    assert result["response_received"] is True
    assert result["close_code"] == 1000


def test_chat_send_is_after_connect_ack_in_frame_chronology() -> None:
    module = load_module()
    result = module.run_case("valid", module.EXPECTED_TOKEN)
    steps = [frame["event"] for frame in result["frames"]]
    assert steps.index("res.connect") < steps.index("req.chat.send")
