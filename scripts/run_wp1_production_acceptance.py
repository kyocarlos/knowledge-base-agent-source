#!/usr/bin/env python3
"""Versioned, fail-closed WP1 controlled acceptance runner.

The runner is intentionally usable against either an isolated candidate or an
explicitly approved local production ingress. It never prints credential,
private-key, signature, or response-content material.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:  # Support both `python scripts/...py` and test-module imports.
    from .prepare_wp1_acceptance_fixture import validate_request_contract
    from .production_run_id_gate import check_unique_production_run_id
    from .websocket_crypto_preflight import (
        CryptoPreflightError,
        crypto_preflight,
        implementation_sha256,
        serialize_connect_payload,
    )
except ImportError:  # pragma: no cover - exercised by direct CLI invocation.
    from prepare_wp1_acceptance_fixture import validate_request_contract
    from production_run_id_gate import check_unique_production_run_id
    from websocket_crypto_preflight import (
        CryptoPreflightError,
        crypto_preflight,
        implementation_sha256,
        serialize_connect_payload,
    )


EXPECTED_SECRET_KEYS = (
    "E2E_AGENT_TOKEN", "E2E_AGENT_ID", "E2E_REVIEWER_TOKEN",
    "E2E_REVIEWER_ID", "E2E_CLEANUP_TOKEN", "E2E_CLEANUP_ID",
)


class AcceptanceGateError(RuntimeError):
    """A gate failed before the runner could safely continue."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def request(url: str, headers: dict[str, str] | None = None, *, method: str = "GET", body: bytes | None = None) -> tuple[int, str]:
    request_headers = dict(headers or {})
    target = urllib.request.Request(url, headers=request_headers, data=body, method=method)
    context = ssl._create_unverified_context() if url.startswith("https://") else None
    try:
        with urllib.request.urlopen(target, timeout=25, context=context) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def post_json(url: str, payload: dict[str, object], headers: dict[str, str] | None = None) -> tuple[int, str]:
    return request(
        url,
        {"Content-Type": "application/json", **(headers or {})},
        method="POST",
        body=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
    )


def post_multipart(url: str, fixture: Path, attachment: Path, headers: dict[str, str]) -> tuple[int, str]:
    boundary = f"----kb-wp1-{hashlib.sha256(os.urandom(32)).hexdigest()}"
    files = (
        ("file", fixture, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("attachments", attachment, "text/plain"),
    )
    parts: list[bytes] = []
    for field, path, mime_type in files:
        parts.extend((
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'.encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            path.read_bytes(),
            b"\r\n",
        ))
    body = b"".join(parts) + f"--{boundary}--\r\n".encode()
    return request(url, {**headers, "Content-Type": f"multipart/form-data; boundary={boundary}", "Content-Length": str(len(body))}, method="POST", body=body)


def parse_json(body: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise AcceptanceGateError(f"{label} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AcceptanceGateError(f"{label} returned non-object JSON")
    return value


def git_head(source_root: Path) -> str:
    return subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()


def pre_network_identity_gate(args: argparse.Namespace, secrets: dict[str, str]) -> dict[str, object]:
    runner = Path(__file__).resolve()
    if git_head(args.source_root) != args.expected_git_head:
        raise AcceptanceGateError("Git HEAD does not equal approved runner commit")
    if sha256(runner) != args.expected_runner_sha256:
        raise AcceptanceGateError("runner SHA-256 does not equal approved runner SHA")
    if implementation_sha256() != args.expected_crypto_sha256:
        raise AcceptanceGateError("crypto implementation SHA-256 does not equal approved SHA")
    if not all((args.expected_commit, args.expected_release_id, args.expected_image_id, args.expected_build_timestamp)):
        raise AcceptanceGateError("candidate identity is incomplete")
    if not args.fixture.is_file() or args.fixture.suffix.lower() != ".xlsx":
        raise AcceptanceGateError("fixture is not an existing .xlsx file")
    if not args.attachment.is_file() or not os.access(args.attachment, os.R_OK):
        raise AcceptanceGateError("required attachment is unavailable")
    if any(not secrets.get(key) for key in EXPECTED_SECRET_KEYS):
        raise AcceptanceGateError("temporary E2E identity credentials are incomplete")
    run_gate = check_unique_production_run_id(args.run_id, args.production_evidence_root)
    contract = validate_request_contract(args.fixture, args.run_id)
    return {
        "git_head": args.expected_git_head,
        "runner_sha256": args.expected_runner_sha256,
        "crypto_sha256": args.expected_crypto_sha256,
        "candidate_identity": "PASS",
        "run_id_uniqueness_gate": run_gate["run_id_uniqueness_gate"],
        "fixture_contract": "PASS",
        "attachment_sha256": sha256(args.attachment),
        "request_contract": contract,
        "network_or_write_started": False,
    }


def verify_runtime_identity(base_url: str, args: argparse.Namespace) -> dict[str, object]:
    health, _ = request(f"{base_url}/health")
    status, body = request(f"{base_url}/api/v1/version")
    payload = parse_json(body, "version") if status == 200 else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    expected = {
        "commit": args.expected_commit,
        "release_id": args.expected_release_id,
        "image_digest": args.expected_image_id,
        "build_timestamp": args.expected_build_timestamp,
    }
    if health != 200 or status != 200 or {key: data.get(key) for key in expected} != expected:
        raise AcceptanceGateError("runtime Health/version identity gate failed")
    return {"health": health, "version": status, "metadata": expected}


def websocket_exchange(base_url: str, run_id: str) -> dict[str, object]:
    status, body = request(f"{base_url}/api/openclaw/chat-config")
    config = parse_json(body, "OpenClaw chat config") if status == 200 else {}
    required = ("authToken", "privateKeyPem", "deviceId", "publicKeyRaw", "sessionKey")
    if status != 200 or any(not config.get(key) for key in required):
        raise AcceptanceGateError("WebSocket Auth Gate credentials are unavailable")
    scopes = list(config.get("scopes") or [])
    if not scopes:
        raise AcceptanceGateError("WebSocket Auth Gate scopes are unavailable")

    async def exchange() -> dict[str, object]:
        import websockets

        ws_url = base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/ws"
        tls = ssl._create_unverified_context() if ws_url.startswith("wss://") else None
        chronology: list[dict[str, object]] = []
        result: dict[str, object] = {"handshake": False, "ready": False, "chat_sent": False, "final": False, "close_code": None, "frames": chronology}
        async with websockets.connect(ws_url, ssl=tls, open_timeout=15, close_timeout=5) as ws:
            result["handshake"] = True
            await ws.send(json.dumps({"type": "auth", "token": config["authToken"]}))
            chronology.append({"direction": "client_to_gateway", "event": "auth", "token_present": True})
            for _ in range(30):
                message = parse_json(await asyncio.wait_for(ws.recv(), timeout=20), "WebSocket frame")
                chronology.append({"direction": "gateway_to_client", "type": message.get("type"), "event": message.get("event"), "id": message.get("id"), "ok": message.get("ok"), "state": (message.get("payload") or {}).get("state")})
                if message.get("event") == "connect.challenge":
                    challenge = message.get("payload") or {}
                    payload = serialize_connect_payload(device_id=str(config["deviceId"]), scopes=scopes, timestamp=int(challenge.get("ts", 0)), token=str(config["authToken"]), nonce=str(challenge.get("nonce", "")))
                    crypto = crypto_preflight(str(config["privateKeyPem"]), payload)
                    signature = base64.urlsafe_b64encode(crypto["signature"]).decode("ascii").rstrip("=")
                    connect = {"type": "req", "id": "c1", "method": "connect", "params": {"minProtocol": 3, "maxProtocol": 3, "client": config.get("client") or {"id": "cli", "version": "1.0.0", "platform": "linux", "mode": "cli"}, "role": "operator", "scopes": scopes, "auth": {"token": config["authToken"], "deviceToken": config.get("deviceToken", "")}, "device": {"id": config["deviceId"], "publicKey": config["publicKeyRaw"], "signature": signature, "signedAt": challenge.get("ts"), "nonce": challenge.get("nonce")}, "locale": config.get("locale", "zh-TW"), "userAgent": config.get("userAgent", "openclaw-e2e/1.0.0")}}
                    await ws.send(json.dumps(connect))
                    chronology.append({"direction": "client_to_gateway", "event": "req.connect", "id": "c1", "crypto": {"key_type": crypto["key_type"], "local_sign": "PASS", "local_verify": "PASS"}})
                elif message.get("type") == "res" and message.get("id") == "c1" and message.get("ok") is True:
                    result["ready"] = True
                    chat = {"type": "req", "id": "wp1-ws-e2e-1", "method": "chat.send", "params": {"sessionKey": config["sessionKey"], "message": "synthetic controlled acceptance probe", "idempotencyKey": run_id}}
                    await ws.send(json.dumps(chat))
                    result["chat_sent"] = True
                    chronology.append({"direction": "client_to_gateway", "event": "req.chat.send", "id": "wp1-ws-e2e-1", "session_present": True})
                elif message.get("event") == "chat" and (message.get("payload") or {}).get("state") in {"final", "end"}:
                    result["final"] = True
                    break
            await ws.close(code=1000)
            result["close_code"] = ws.close_code
        return result

    result = asyncio.run(exchange())
    if not all((result["handshake"], result["ready"], result["chat_sent"], result["final"], result["close_code"] == 1000)):
        raise AcceptanceGateError("WebSocket protocol acceptance failed")
    return result


def run_acceptance(args: argparse.Namespace) -> dict[str, object]:
    secrets = read_env(args.credentials_env)
    evidence: dict[str, object] = {"run_id": args.run_id, "production_touched": args.production, "secrets_included": False}
    evidence["pre_network_identity_gate"] = pre_network_identity_gate(args, secrets)
    evidence["runtime_identity"] = verify_runtime_identity(args.base_url.rstrip("/"), args)
    base = args.base_url.rstrip("/")
    agent = {"Authorization": f"Bearer {secrets['E2E_AGENT_TOKEN']}", "X-E2E-Agent-ID": secrets["E2E_AGENT_ID"], "X-E2E-Test-Mode": "true", "X-E2E-Test-Run-ID": args.run_id, "Idempotency-Key": args.run_id}
    reviewer = {"Authorization": f"Bearer {secrets['E2E_REVIEWER_TOKEN']}", "X-E2E-Reviewer-ID": secrets["E2E_REVIEWER_ID"], "X-E2E-Test-Mode": "true"}
    cleanup = {"Authorization": f"Bearer {secrets['E2E_CLEANUP_TOKEN']}", "X-E2E-Cleanup-ID": secrets["E2E_CLEANUP_ID"]}
    submission_id: str | None = None
    try:
        search_status, search_body = post_json(f"{base}/search", {"query": "synthetic acceptance probe", "mode": "basic", "sources_only": True}, {"X-Trace-ID": args.run_id})
        evidence["search"] = {"status": search_status, "task_id_present": bool(parse_json(search_body, "search").get("task_id"))}
        if search_status != 200 or not evidence["search"]["task_id_present"]:
            raise AcceptanceGateError("Search gate failed")
        upload_status, upload_body = post_multipart(f"{base}/api/agent/v1/reports", args.fixture, args.attachment, agent)
        upload = parse_json(upload_body, "upload")
        submission_id = str(upload.get("submission_id") or "") or None
        evidence["upload"] = {"status": upload_status, "submission_id_present": bool(submission_id)}
        if upload_status != 202 or not submission_id:
            raise AcceptanceGateError("Upload gate failed")
        duplicate_status, duplicate_body = post_multipart(f"{base}/api/agent/v1/reports", args.fixture, args.attachment, agent)
        duplicate = parse_json(duplicate_body, "duplicate")
        evidence["duplicate"] = {"status": duplicate_status, "duplicate": duplicate.get("duplicate")}
        if duplicate_status != 202 or duplicate.get("duplicate") is not True:
            raise AcceptanceGateError("Duplicate/idempotency gate failed")
        self_read_status, _ = request(f"{base}/api/agent/v1/reports/{submission_id}", {"Authorization": agent["Authorization"], "X-Agent-ID": agent["X-E2E-Agent-ID"]})
        evidence["self_read"] = self_read_status
        if self_read_status != 200:
            raise AcceptanceGateError("Report self-read gate failed")
        approve_status, _ = post_json(f"{base}/api/admin/v1/report-submissions/{submission_id}/approve", {"comment": "controlled synthetic acceptance"}, reviewer)
        evidence["approve"] = approve_status
        if approve_status != 200:
            raise AcceptanceGateError("Report approval gate failed")
        terminal = None
        for _ in range(args.ingest_poll_attempts):
            status, body = request(f"{base}/api/admin/v1/report-submissions/{submission_id}", reviewer)
            item = parse_json(body, "report status") if status == 200 else {}
            terminal = item.get("status")
            if terminal in {"completed", "ingest_failed", "rejected", "validation_failed"}:
                break
            time.sleep(args.ingest_poll_interval)
        evidence["ingest_terminal"] = terminal
        if terminal != "completed":
            raise AcceptanceGateError("Ingest completion gate failed")
        evidence["websocket"] = websocket_exchange(base, args.run_id)
        dry_status, dry_body = post_json(f"{base}/api/internal/e2e/v1/runs/{args.run_id}/cleanup", {"environment": "anritsu", "apply": False}, cleanup)
        apply_status, apply_body = post_json(f"{base}/api/internal/e2e/v1/runs/{args.run_id}/cleanup", {"environment": "anritsu", "apply": True}, cleanup)
        dry = parse_json(dry_body, "cleanup dry-run")
        applied = parse_json(apply_body, "cleanup apply")
        evidence["cleanup"] = {"dry_run_status": dry_status, "dry_run_mode": dry.get("mode"), "apply_status": apply_status, "apply_mode": applied.get("mode")}
        if dry_status != 200 or dry.get("mode") != "dry-run" or apply_status != 200 or applied.get("mode") != "apply":
            raise AcceptanceGateError("Cleanup gate failed")
        post_status, _ = request(f"{base}/api/admin/v1/report-submissions/{submission_id}", reviewer)
        evidence["post_cleanup_lookup"] = post_status
        if post_status != 404:
            raise AcceptanceGateError("Post-cleanup lookup gate failed")
        evidence.update({"residual_count": 0, "result": "PASS"})
    except Exception as exc:  # cleanup is best effort; the caller owns rollback.
        evidence.update({"result": "FAIL", "error_type": type(exc).__name__, "error": str(exc)})
        if submission_id:
            try:
                status, _ = post_json(f"{base}/api/internal/e2e/v1/runs/{args.run_id}/cleanup", {"environment": "anritsu", "apply": True}, cleanup)
                evidence["failure_cleanup_status"] = status
            except Exception as cleanup_exc:  # noqa: BLE001
                evidence["failure_cleanup_status"] = f"PARTIAL_FAIL:{type(cleanup_exc).__name__}"
        raise
    finally:
        args.evidence_out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--attachment", type=Path, required=True)
    parser.add_argument("--credentials-env", type=Path, required=True)
    parser.add_argument("--production-evidence-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-git-head", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--expected-crypto-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-release-id", required=True)
    parser.add_argument("--expected-image-id", required=True)
    parser.add_argument("--expected-build-timestamp", required=True)
    parser.add_argument("--evidence-out", type=Path, required=True)
    parser.add_argument("--ingest-poll-attempts", type=int, default=45)
    parser.add_argument("--ingest-poll-interval", type=float, default=2.0)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    if args.production and args.base_url not in {"https://127.0.0.1:3030", "https://localhost:3030"}:
        raise AcceptanceGateError("production runner accepts only the approved local formal ingress")
    if not args.production and not args.base_url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise AcceptanceGateError("isolated runner accepts only localhost endpoints")
    args.evidence_out.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_acceptance(args)
    except (AcceptanceGateError, CryptoPreflightError, OSError, ValueError) as exc:
        print(f"acceptance failed closed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps({"result": "PASS", "run_id": args.run_id, "secrets_included": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
