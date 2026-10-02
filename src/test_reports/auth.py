"""Hash-only bearer-token authentication for report agents and reviewers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os

from fastapi import HTTPException, Request


def token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _bearer_token(request: Request) -> str:
    value = request.headers.get("Authorization", "")
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="缺少 Bearer token")
    return token.strip()


def _load_json_env(name: str) -> dict:
    raw = os.getenv(name, "").strip()
    if not raw:
        raise HTTPException(status_code=503, detail=f"伺服器尚未設定 {name}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=503, detail=f"{name} 設定格式錯誤") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=503, detail=f"{name} 必須是 JSON object")
    return value


def authenticate_agent(request: Request) -> dict:
    agent_id = request.headers.get("X-Agent-ID", "").strip()
    if not agent_id:
        raise HTTPException(status_code=401, detail="缺少 X-Agent-ID")
    agent = _load_json_env("KB_AGENT_TOKEN_HASHES_JSON").get(agent_id)
    if not isinstance(agent, dict):
        raise HTTPException(status_code=403, detail="未知的 Agent")
    expected = str(agent.get("token_sha256") or "").lower()
    actual = token_sha256(_bearer_token(request))
    if not expected or not hmac.compare_digest(expected, actual):
        raise HTTPException(status_code=403, detail="Agent token 無效")
    environment = str(agent.get("environment") or "").lower()
    if environment not in {"anritsu", "amarisoft"}:
        raise HTTPException(status_code=503, detail="Agent environment 設定錯誤")
    return {"agent_id": agent_id, "environment": environment, "scope": "report:upload"}


def authenticate_reviewer(request: Request) -> dict:
    config = _load_json_env("KB_REVIEWER_TOKEN_HASHES_JSON")
    actual = token_sha256(_bearer_token(request))
    for reviewer_id, expected in config.items():
        expected_hash = expected.get("token_sha256") if isinstance(expected, dict) else expected
        if expected_hash and hmac.compare_digest(str(expected_hash).lower(), actual):
            return {"reviewer_id": reviewer_id, "scope": "report:review"}
    raise HTTPException(status_code=403, detail="Reviewer token 無效")
