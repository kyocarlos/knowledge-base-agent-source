"""Hash-only bearer-token authentication for report agents and reviewers."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path

from fastapi import HTTPException, Request


SAFE_TEST_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


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


def _csit_download_signing_key() -> bytes:
    """Derive an internal signing key without exposing the reader token."""
    raw = os.getenv("KB_CSIT_READER_TOKEN_HASHES_JSON", "").strip()
    if not raw:
        password_file = os.getenv("CSIT_PASSWORD_FILE", "").strip()
        if password_file:
            try:
                raw = Path(password_file).read_text(encoding="utf-8").strip()
            except OSError:
                raw = ""
        if not raw:
            raw = os.getenv("CSIT_PASSWORD", "").strip()
    if not raw:
        return b""
    return hashlib.sha256(("km-csit-download-v1:" + raw).encode("utf-8")).digest()


def safe_csit_filename(filename: str, fallback: str = "download.bin") -> str:
    """Keep only a safe basename for a browser download."""
    value = str(filename or "").replace("\\", "/").split("/")[-1]
    value = re.sub(r"[\x00-\x1f\x7f\"']", "_", value).strip(" .")
    return value[:180] or fallback


def create_csit_download_ticket(file_id: str, filename: str = "", ttl_seconds: int = 300) -> str:
    """Create a short-lived opaque ticket for one CSIT file download."""
    normalized = str(file_id or "").strip()
    key = _csit_download_signing_key()
    if not normalized or not key:
        return ""
    expires = int(time.time()) + max(30, min(int(ttl_seconds), 900))
    safe_name = safe_csit_filename(filename, "download.bin")
    payload = f"{normalized}|{expires}|{safe_name}".encode("utf-8")
    encoded = __import__("base64").urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")
    signature = hmac.new(key, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def verify_csit_download_ticket(file_id: str, ticket: str) -> bool:
    """Verify ticket integrity, expiry, and binding to the requested file."""
    key = _csit_download_signing_key()
    if not key or not ticket or "." not in ticket:
        return False
    encoded, signature = ticket.split(".", 1)
    expected = hmac.new(key, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = __import__("base64").urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        ticket_file_id, expires, _filename = payload.split("|", 2)
        return hmac.compare_digest(ticket_file_id, str(file_id or "").strip()) and int(expires) >= int(time.time())
    except (ValueError, UnicodeError):
        return False


def csit_download_ticket_filename(file_id: str, ticket: str) -> str:
    """Return the signed safe filename, or an empty string when invalid."""
    if not verify_csit_download_ticket(file_id, ticket):
        return ""
    encoded = ticket.split(".", 1)[0]
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = __import__("base64").urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        ticket_file_id, _expires, filename = payload.split("|", 2)
        if not hmac.compare_digest(ticket_file_id, str(file_id or "").strip()):
            return ""
        return safe_csit_filename(filename)
    except (ValueError, UnicodeError):
        return ""


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


def authenticate_csit_reader(request: Request) -> dict:
    """Authenticate the separately scoped, read-only CSIT proxy."""
    path_file_id = getattr(request, "path_params", {}).get("file_id")
    ticket = getattr(request, "query_params", {}).get("ticket", "")
    if path_file_id and verify_csit_download_ticket(path_file_id, ticket):
        return {"scope": "csit:download", "file_id": path_file_id, "ticket": "valid"}
    identity = request.headers.get("X-CSIT-Reader-ID", "").strip()
    if not identity:
        raise HTTPException(status_code=401, detail="缺少 X-CSIT-Reader-ID")
    config = _load_json_env("KB_CSIT_READER_TOKEN_HASHES_JSON")
    expected = config.get(identity)
    if expected is None:
        raise HTTPException(status_code=403, detail="未知的 CSIT reader")
    expected_hash = expected.get("token_sha256") if isinstance(expected, dict) else expected
    actual = token_sha256(_bearer_token(request))
    if not expected_hash or not hmac.compare_digest(str(expected_hash).lower(), actual):
        raise HTTPException(status_code=403, detail="CSIT reader token 無效")
    return {"reader_id": identity, "scope": "csit:read"}


def authenticate_e2e_cleanup(request: Request) -> dict:
    """Authenticate the separately scoped, normally disabled E2E cleanup API."""
    cleanup_id = request.headers.get("X-E2E-Cleanup-ID", "").strip()
    if not cleanup_id:
        raise HTTPException(status_code=401, detail="缺少 X-E2E-Cleanup-ID")
    config = _load_json_env("KB_E2E_CLEANUP_TOKEN_HASHES_JSON")
    expected = config.get(cleanup_id)
    expected_hash = expected.get("token_sha256") if isinstance(expected, dict) else expected
    actual = token_sha256(_bearer_token(request))
    if not expected_hash or not hmac.compare_digest(str(expected_hash).lower(), actual):
        raise HTTPException(status_code=403, detail="E2E cleanup token 無效")
    return {"cleanup_id": cleanup_id, "scope": "e2e:cleanup"}


def _authenticate_e2e_identity(request: Request, config_name: str, header_name: str, scope: str) -> dict:
    identity = request.headers.get(header_name, "").strip()
    if not identity:
        raise HTTPException(status_code=401, detail=f"缺少 {header_name}")
    config = _load_json_env(config_name)
    expected = config.get(identity)
    expected_hash = expected.get("token_sha256") if isinstance(expected, dict) else expected
    actual = token_sha256(_bearer_token(request))
    if not expected_hash or not hmac.compare_digest(str(expected_hash).lower(), actual):
        raise HTTPException(status_code=403, detail="E2E credential 無效")
    result = {"identity": identity, "scope": scope}
    if scope == "report:upload":
        result["agent_id"] = identity
    elif scope == "report:review":
        result["reviewer_id"] = identity
    if isinstance(expected, dict) and expected.get("environment"):
        result["environment"] = str(expected["environment"]).lower()
    return result


def authenticate_e2e_agent(request: Request) -> dict:
    return _authenticate_e2e_identity(request, "KB_E2E_AGENT_TOKEN_HASHES_JSON", "X-E2E-Agent-ID", "report:upload")


def authenticate_e2e_reviewer(request: Request) -> dict:
    return _authenticate_e2e_identity(request, "KB_E2E_REVIEWER_TOKEN_HASHES_JSON", "X-E2E-Reviewer-ID", "report:review")


def e2e_write_enabled() -> bool:
    return os.getenv("KB_E2E_WRITE_MODE_ENABLED", "false").lower() in {"1", "true", "yes"}


def validate_e2e_test_run_id(test_run_id: str) -> str:
    prefix = os.getenv("KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX", "").strip()
    value = str(test_run_id or "").strip()
    if not prefix or not SAFE_TEST_RUN_ID.fullmatch(value) or not value.startswith(prefix):
        raise HTTPException(status_code=422, detail="test_run_id 不符合 E2E 測試 prefix")
    return value


def authenticate_report_agent(request: Request) -> dict:
    if request.headers.get("X-E2E-Test-Mode", "").strip().lower() == "true":
        if not e2e_write_enabled():
            raise HTTPException(status_code=404, detail="E2E write mode disabled")
        identity = authenticate_e2e_agent(request)
        identity["e2e"] = True
        return identity
    return authenticate_agent(request)


def authenticate_report_reviewer(request: Request) -> dict:
    if request.headers.get("X-E2E-Test-Mode", "").strip().lower() == "true":
        if not e2e_write_enabled():
            raise HTTPException(status_code=404, detail="E2E write mode disabled")
        identity = authenticate_e2e_reviewer(request)
        identity["e2e"] = True
        return identity
    return authenticate_reviewer(request)
