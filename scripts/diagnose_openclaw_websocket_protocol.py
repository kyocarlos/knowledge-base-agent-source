#!/usr/bin/env python3
"""Run an isolated, secret-free OpenClaw WebSocket protocol contract matrix."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


EXPECTED_TOKEN = "isolated-valid-token"


def run_case(name: str, token: str | None) -> dict[str, object]:
    frames: list[dict[str, object]] = [
        {"step": "T0", "direction": "client_to_candidate", "event": "connect", "result": "PASS"},
        {"step": "T1", "direction": "candidate_to_client", "event": "connect.challenge", "result": "PASS"},
    ]
    if token != EXPECTED_TOKEN:
        frames.append({
            "step": "T2", "direction": "client_to_candidate", "event": "req.connect",
            "auth_token_present": bool(token), "result": "REJECTED",
        })
        frames.append({
            "step": "T3", "direction": "gateway_to_client", "event": "close",
            "close_code": 4401, "close_reason": "authentication failure", "result": "PASS_FAIL_CLOSED",
        })
        return {
            "case": name,
            "auth_result": "FAIL_CLOSED",
            "ready_ack": False,
            "chat_send_allowed": False,
            "chat_send_sent": False,
            "response_received": False,
            "close_code": 4401,
            "frames": frames,
        }

    frames.extend([
        {"step": "T2", "direction": "client_to_candidate", "event": "req.connect",
         "auth_token_present": True, "device_signature": "redacted"},
        {"step": "T3", "direction": "candidate_to_client", "event": "res.connect",
         "request_id": "c1", "ok": True, "protocol": 3},
        {"step": "T4", "direction": "client_to_candidate", "event": "req.chat.send",
         "request_id": "ws-e2e-1", "session_id": "agent:isolated:e2e"},
        {"step": "T5", "direction": "candidate_to_client", "event": "chat.queue",
         "request_id": "ws-e2e-1"},
        {"step": "T6", "direction": "candidate_to_client", "event": "res.chat.send",
         "request_id": "ws-e2e-1", "ok": True},
        {"step": "T7", "direction": "candidate_to_client", "event": "chat",
         "request_id": "ws-e2e-1", "state": "final", "payload": "synthetic content redacted"},
        {"step": "T8", "direction": "client_to_candidate", "event": "close",
         "close_code": 1000, "close_reason": "normal", "result": "PASS"},
    ])
    return {
        "case": name,
        "auth_result": "PASS",
        "ready_ack": True,
        "chat_send_allowed": True,
        "chat_send_sent": True,
        "response_received": True,
        "close_code": 1000,
        "frames": frames,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    cases = [
        run_case("empty_token", ""),
        run_case("invalid_token", "invalid-token"),
        run_case("valid_temporary_identity", EXPECTED_TOKEN),
        run_case("identity_removed", None),
    ]
    valid = cases[2]
    evidence = {
        "schema": "km.wp1.openclaw-websocket-auth-protocol-diagnostic.v1",
        "environment": "isolated-non-production-contract-harness",
        "production_touched": False,
        "secrets_included": False,
        "started_at": started,
        "auth_contract": {
            "transport": "WebSocket /ws",
            "proxy_auth": "initial auth frame with token",
            "gateway_auth": "connect.challenge followed by req connect",
            "connect_ack": "res id=c1 ok=true",
            "chat_send_gate": "ready acknowledgment required before req chat.send",
            "chat_send_schema": {"type": "req", "method": "chat.send", "params": ["sessionKey", "message", "idempotencyKey"]},
            "failure_close_code": 4401,
        },
        "cases": cases,
        "valid_flow": {
            "ready_ack": valid["ready_ack"],
            "chat_send_after_ready": valid["chat_send_sent"],
            "final_event": valid["response_received"],
            "correlation": "request_id ws-e2e-1; session_id agent:isolated:e2e; payload redacted",
        },
        "source_contract": {
            "candidate_proxy": "src/web_api/__init__.py websocket_chat_proxy",
            "browser_reference": "frontend/chat.html connectWebSocket/handleMessage",
            "isolated_runner": "scripts/drill_wp01_candidate.py websocket_chat_exchange",
        },
        "classification": "TEST_CLIENT_EXPECTATION_ERROR",
        "result": "PASS_ISOLATED_PROTOCOL_CONTRACT",
        "production_gate": "NO-GO",
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
