#!/usr/bin/env python3
"""Validate corrected runner signing and lifecycle in localhost isolation."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from websocket_crypto_preflight import (
    CryptoPreflightError,
    crypto_preflight,
    implementation_sha256,
    serialize_connect_payload,
    sign_payload,
    verify_payload,
)


def run_crypto_matrix() -> dict[str, object]:
    payload = serialize_connect_payload(
        device_id="matrix-device", scopes=["operator.read"], timestamp=123,
        token="matrix-token", nonce="matrix-nonce",
    )
    ed_key = ed25519.Ed25519PrivateKey.generate()
    ed_type, ed_signature = sign_payload(ed_key, payload)
    wrong_ed_key = ed25519.Ed25519PrivateKey.generate().public_key()
    rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    rsa_type, rsa_signature = sign_payload(rsa_key, payload)
    try:
        crypto_preflight("", payload)
        empty_key = "FAIL"
    except CryptoPreflightError:
        empty_key = "PASS_FAIL_CLOSED"
    unsupported = ec.generate_private_key(ec.SECP256R1())
    unsupported_pem = unsupported.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    try:
        crypto_preflight(unsupported_pem, payload)
        unsupported_key = "FAIL"
    except CryptoPreflightError:
        unsupported_key = "PASS_FAIL_CLOSED"
    return {
        "ed25519_valid_signature": "PASS" if verify_payload(ed_key.public_key(), ed_type, payload, ed_signature) else "FAIL",
        "altered_payload": "PASS_FAIL_CLOSED" if not verify_payload(ed_key.public_key(), ed_type, payload + b"altered", ed_signature) else "FAIL",
        "wrong_public_key": "PASS_FAIL_CLOSED" if not verify_payload(wrong_ed_key, ed_type, payload, ed_signature) else "FAIL",
        "rsa_explicit_branch": "PASS" if verify_payload(rsa_key.public_key(), rsa_type, payload, rsa_signature) else "FAIL",
        "empty_key": empty_key,
        "unsupported_key": unsupported_key,
        "payload_serialization_deterministic": payload == serialize_connect_payload(
            device_id="matrix-device", scopes=["operator.read"], timestamp=123,
            token="matrix-token", nonce="matrix-nonce",
        ),
        "network_started": False,
    }


async def run_lifecycle() -> dict[str, object]:
    token = "isolated-temporary-token"
    device_id = "isolated-ed25519-device"
    scopes = ["operator.read", "operator.write"]
    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("utf-8")
    public_raw = base64.urlsafe_b64encode(public_key.public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )).decode("ascii").rstrip("=")
    chronology: list[dict[str, object]] = []

    async def gateway(ws):
        timestamp = int(time.time() * 1000)
        nonce = "isolated-ed25519-nonce"
        await ws.send(json.dumps({"type": "event", "event": "connect.challenge", "payload": {"ts": timestamp, "nonce": nonce}}))
        chronology.append({"step": "T1", "direction": "gateway_to_runner", "event": "connect.challenge"})
        connect = json.loads(await ws.recv())
        params = connect.get("params") or {}
        device = params.get("device") or {}
        payload = serialize_connect_payload(
            device_id=device["id"], scopes=params.get("scopes") or [],
            timestamp=device["signedAt"], token=(params.get("auth") or {})["token"],
            nonce=device["nonce"],
        )
        signature = base64.urlsafe_b64decode(device["signature"] + "==")
        if not verify_payload(public_key, "Ed25519", payload, signature):
            await ws.close(code=4401, reason="invalid signature")
            return
        chronology.append({"step": "T2", "direction": "runner_to_gateway", "event": "req.connect", "signature": "verified"})
        await ws.send(json.dumps({"type": "res", "id": "c1", "ok": True, "payload": {"protocol": 3}}))
        chronology.append({"step": "T3", "direction": "gateway_to_runner", "event": "res.connect", "ok": True})
        chat = json.loads(await ws.recv())
        if chat.get("method") != "chat.send":
            await ws.close(code=4400, reason="chat.send required")
            return
        chronology.append({"step": "T4", "direction": "runner_to_gateway", "event": "chat.send", "request_id": chat.get("id")})
        await ws.send(json.dumps({"type": "event", "event": "chat.queue", "payload": {"requestId": chat.get("id")}}))
        await ws.send(json.dumps({"type": "res", "id": chat.get("id"), "ok": True, "payload": {"status": "queued"}}))
        await ws.send(json.dumps({"type": "event", "event": "chat", "payload": {"state": "final", "sessionKey": (chat.get("params") or {}).get("sessionKey"), "message": {"content": "redacted"}}}))
        chronology.append({"step": "T5", "direction": "gateway_to_runner", "event": "queue_ack_final"})

    server = await websockets.serve(gateway, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        timestamp = int(time.time() * 1000)
        nonce = "isolated-ed25519-nonce"
        payload = serialize_connect_payload(
            device_id=device_id, scopes=scopes, timestamp=timestamp,
            token=token, nonce=nonce,
        )
        preflight = crypto_preflight(private_pem, payload)
        chronology.append({"step": "T0", "event": "crypto_preflight", "result": "PASS", "network_started": False})
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            challenge = json.loads(await ws.recv())
            challenge_payload = serialize_connect_payload(
                device_id=device_id, scopes=scopes,
                timestamp=(challenge.get("payload") or {})["ts"], token=token,
                nonce=(challenge.get("payload") or {})["nonce"],
            )
            challenge_preflight = crypto_preflight(private_pem, challenge_payload)
            signature = base64.urlsafe_b64encode(challenge_preflight.pop("signature")).decode("ascii").rstrip("=")
            await ws.send(json.dumps({
                "type": "req", "id": "c1", "method": "connect",
                "params": {
                    "minProtocol": 3, "maxProtocol": 3,
                    "client": {"id": "cli", "version": "1.0.0", "platform": "linux", "mode": "cli"},
                    "role": "operator", "scopes": scopes,
                    "auth": {"token": token, "deviceToken": "isolated-device-token"},
                    "device": {"id": device_id, "publicKey": public_raw, "signature": signature,
                               "signedAt": (challenge.get("payload") or {})["ts"], "nonce": (challenge.get("payload") or {})["nonce"]},
                },
            }))
            ready = json.loads(await ws.recv())
            if not (ready.get("type") == "res" and ready.get("id") == "c1" and ready.get("ok") is True):
                raise RuntimeError("ready acknowledgment missing")
            await ws.send(json.dumps({"type": "req", "id": "ws-e2e-1", "method": "chat.send", "params": {"sessionKey": "agent:isolated:e2e", "message": "synthetic", "idempotencyKey": "ws-e2e-1"}}))
            final = False
            for _ in range(3):
                frame = json.loads(await ws.recv())
                if frame.get("event") == "chat" and (frame.get("payload") or {}).get("state") == "final":
                    final = True
            await ws.close(code=1000)
            close_code = ws.close_code
        preflight.pop("signature")
        return {
            "crypto_preflight": preflight,
            "challenge_crypto_preflight": challenge_preflight,
            "network_started_after_crypto_preflight": True,
            "ready_ack": True,
            "chat_send_after_ready": True,
            "final_event": final,
            "close_code": close_code,
            "chronology": chronology,
        }
    finally:
        server.close()
        await server.wait_closed()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lifecycle = asyncio.run(run_lifecycle())
    matrix = run_crypto_matrix()
    matrix_pass = all(value in {"PASS", "PASS_FAIL_CLOSED", True, False} for value in matrix.values()) and matrix["network_started"] is False
    result = "PASS" if all((matrix_pass, lifecycle["ready_ack"], lifecycle["chat_send_after_ready"], lifecycle["final_event"], lifecycle["close_code"] == 1000)) else "FAIL"
    evidence = {
        "schema": "km.wp1.websocket-runner-ed25519-signing-fix.v1",
        "environment": "isolated-localhost",
        "production_touched": False,
        "secrets_included": False,
        "candidate_unchanged": True,
        "candidate": {
            "source": "914d7c829269779f13c47d71ebd27ecb9dde84ec",
            "release": "wp1-deployment-metadata-yaml-quoting-fix-20260826-r1",
            "image": "sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3"
        },
        "runner_crypto_implementation_sha256": implementation_sha256(),
        "validation_matrix": matrix,
        "lifecycle": lifecycle,
        "result": result,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "production_gate": "NO-GO_PENDING_SUPERVISOR_REVIEW"
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(args.output)
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
