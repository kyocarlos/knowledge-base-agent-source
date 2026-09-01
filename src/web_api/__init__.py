"""
FastAPI Web 服務 - 知識庫系統
支援多人同時查詢，任務異步化
"""

import logging
import re
import base64
import hashlib
import asyncio
import uuid
import time
import urllib.request
from typing import Optional, List
from collections import deque
from datetime import datetime
from contextlib import asynccontextmanager, suppress
import os
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field
from celery.result import AsyncResult
from celery.app.control import Inspect
import yaml

from ..compare_rules import is_compare_like_query
from .tasks import search_task
from app.core.job_config import celery_headers
from .cache import cache_get, cache_set
from ..storage_paths import resolve_storage_category

WORKSPACE_DIR = "/home/da40_ai_gb10/.openclaw/workspace"
UPLOAD_RETENTION_LIMIT = 10

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ===== Pydantic Models =====

class ReportSearchFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: Optional[List[str] | str] = None
    run_id: Optional[List[str] | str] = None
    project_code: Optional[List[str] | str] = None
    dut_model: Optional[List[str] | str] = None
    band: Optional[List[str] | str] = None
    protocol: Optional[List[str] | str] = None
    direction: Optional[List[str] | str] = None
    verdict: Optional[List[str] | str] = None
    schema_version: Optional[List[str] | str] = None
    source_system: Optional[List[str] | str] = None
    environment_id: Optional[List[str] | str] = None
    project_id: Optional[List[str] | str] = None
    artifact_type: Optional[List[str] | str] = None
    report_schema: Optional[List[str] | str] = None
    document_id: Optional[List[str] | str] = None
    idempotency_key: Optional[List[str] | str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    mode: str = "auto"  # "basic", "deep", "vector", "hybrid", "auto"
    user_id: Optional[str] = None
    top_k: Optional[int] = None
    sources_only: bool = False
    filters: Optional[ReportSearchFilters] = None


class SearchResponse(BaseModel):
    task_id: str
    status: str
    message: str


class KnowledgeRevisionRequest(BaseModel):
    package_id: str
    document_id: str
    document_version: str
    publish_status: str = "draft"


class KnowledgeRevisionTransition(BaseModel):
    target: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    answer: Optional[str] = None
    sources: Optional[list] = None
    citation_distribution: Optional[dict] = None
    mode: Optional[str] = None
    error: Optional[str] = None
    queue_position: Optional[int] = None  # 排隊位置（前方還有多少任務）

class CategoryRelevanceRequest(BaseModel):
    query: str
    top_k: int = 20


class CategoryRelevanceResponse(BaseModel):
    categories: dict
    query: str


class AnalyzeQuestionRequest(BaseModel):
    query: str


class AnalyzeQuestionResponse(BaseModel):
    category_scores: dict
    normalized_scores: dict = Field(default_factory=dict)
    related_docs: dict
    query: str

    top_category: Optional[str] = None
    top_score: Optional[float] = None
    confidence: Optional[float] = None
    analysis_method: Optional[str] = None
    estimated_wait_seconds: Optional[int] = None  # 預估等待秒數


class SourceCategoryRequest(BaseModel):
    sources: List[str] = Field(default_factory=list)


class SourceCategoryResponse(BaseModel):
    categories: dict
    source_categories: dict = Field(default_factory=dict)
    matched_count: int
    unmatched_count: int


class ChunkEditRequest(BaseModel):
    content: str


CATEGORY_ORDER = ["4G/5G", "WiFi", "Lab", "Project", "Automation"]

DOCUMENT_FILE_EXTENSIONS = (".md", ".txt", ".MD")

DOCUMENT_CATEGORY_MAPPING = {
    "4G/5G": "4G_5G",
    "4G_5G": "4G_5G",
    "4g5g": "4G_5G",
    "Report": "Report",
    "report": "Report",
    "WiFi": "WiFi",
    "Lab": "Lab",
    "Project": "Project",
    "Automation": "Automation",
    "Simple": "Simple",
    "simple": "Simple",
    "實驗室管理": "Lab",
    "專案": "Project",
    "自動化": "Automation",
    "專案管理": "Project",
    "自動化管理": "Automation",
}


def _load_data_base() -> Path:
    """取得資料根目錄。"""
    project_root = Path(__file__).resolve().parents[2]
    config_path = project_root / "config" / "config.yaml"
    if not config_path.exists():
        config_path = Path("/home/da40_ai_gb10/knowledge-base/config/config.yaml")
    with open(config_path) as f:
        config = yaml.safe_load(f)
    return Path(config.get("data", {}).get("base", "/home/da40_ai_gb10/knowledge-base/data"))


def _normalize_document_lookup_name(doc_name: str) -> tuple[str, str]:
    """把前端傳入的文件名稱轉成可用的查找名稱。"""
    requested_name = os.path.basename(str(doc_name or "").strip())
    requested_stem = os.path.splitext(requested_name)[0]
    return requested_name, requested_stem


def _iter_document_metadata_files(data_base: Path) -> list[Path]:
    """掃描所有 source metadata，讓文件解析能涵蓋 processed 與 uploads。"""
    metadata_files: list[Path] = []
    for root in (data_base / "processed", data_base / "uploads"):
        if not root.exists():
            continue
        metadata_files.extend(sorted(root.rglob("*.source.json")))
    return metadata_files


def _read_document_text(path: Path) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _find_document_content(data_base: Path, category: str, doc_name: str) -> tuple[str | None, Path | None, list[str]]:
    """
    依文件名稱尋找內容。

    優先順序：
    1. 類別目錄內直接命中
    2. uploads / processed 的對應 converted 檔
    3. 透過 source.json 回推 converted_path
    4. 全資料根目錄遞迴查找
    """
    actual_category = DOCUMENT_CATEGORY_MAPPING.get(category, category)
    requested_name, requested_stem = _normalize_document_lookup_name(doc_name)
    if not requested_name:
        return None, None, []

    search_roots = [
        data_base / "processed" / actual_category,
        data_base / "uploads" / actual_category,
        data_base / "processed",
        data_base / "uploads",
        data_base,
    ]

    tried_paths: list[str] = []

    def add_direct_candidates(root: Path) -> list[Path]:
        candidates: list[Path] = []
        for ext in DOCUMENT_FILE_EXTENSIONS:
            candidates.append(root / f"{requested_stem}{ext}")
        return candidates

    for root in search_roots:
        if not root.exists():
            continue
        for candidate in add_direct_candidates(root):
            tried_paths.append(str(candidate))
            text = _read_document_text(candidate)
            if text is not None:
                return text, candidate, tried_paths

        # 有些文件會藏在 uploads/<category>/.../converted/ 底下，直接遞迴補查。
        for ext in DOCUMENT_FILE_EXTENSIONS:
            for candidate in root.rglob(f"{requested_stem}{ext}"):
                tried_paths.append(str(candidate))
                text = _read_document_text(candidate)
                if text is not None:
                    return text, candidate, tried_paths

    # 透過 source metadata 回推 converted_path/original_path，涵蓋 uploaded WiFi 這種未落到 processed 的文件。
    requested_lower = requested_name.lower()
    requested_stem_lower = requested_stem.lower()
    for meta_path in _iter_document_metadata_files(data_base):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue

        source_name = os.path.basename(str(meta.get("source_name") or ""))
        source_stem = str(meta.get("source_stem") or "").strip()
        original_path = str(meta.get("original_path") or "").strip()
        converted_path = str(meta.get("converted_path") or "").strip()
        metadata_haystack = " ".join(
            [
                source_name,
                source_stem,
                os.path.basename(original_path),
                os.path.basename(converted_path),
            ]
        ).lower()

        if requested_lower not in metadata_haystack and requested_stem_lower not in metadata_haystack:
            continue

        for candidate_path in (converted_path, original_path):
            if not candidate_path:
                continue
            candidate = Path(candidate_path)
            tried_paths.append(str(candidate))
            text = _read_document_text(candidate)
            if text is not None:
                return text, candidate, tried_paths

    return None, None, tried_paths

CATEGORY_WEIGHT_PROFILES = {
    "4G/5G": {
        "keywords": [
            "4g/5g", "4g5g", "5g", "lte", "nr", "nsa", "sa",
            "基站", "基地台", "nr基站", "小基站", "handover",
            "beamforming", "beam", "volte", "scell", "ca",
            "rlc", "pdcp", "ngap", "pdsch", "amr", "scu",
            "頻段", "傳輸速率", "調變", "天線", "無線接入"
        ],
        "boost_keywords": ["5G", "LTE", "NR", "RLC", "PDCP", "NGAP"],
    },
    "WiFi": {
        "keywords": [
            "wifi", "wi-fi", "ssid", "ap", "access point", "mesh",
            "channel", "頻道", "wpa", "wpa2", "wpa3", "router",
            "802.11", "wifi6", "wifi7", "6ghz", "5ghz", "2.4ghz"
        ],
        "boost_keywords": ["WiFi", "SSID", "AP", "Mesh"],
    },
    "Lab": {
        "keywords": [
            "lab", "設備", "器材", "儀器", "borrow", "borrower",
            "借用", "歸還", "校正", "calibration", "safety",
            "inventory", "實驗室", "測試床", "測試台"
        ],
        "boost_keywords": ["Lab", "Equipment", "Borrower", "Calibration"],
    },
    "Project": {
        "keywords": [
            "project", "pm", "milestone", "risk", "task", "progress",
            "deliverable", "schedule", "deadline", "專案", "里程碑",
            "風險", "進度", "任務", "客戶", "部門"
        ],
        "boost_keywords": ["Project", "PM", "Milestone", "Risk"],
    },
    "Automation": {
        "keywords": [
            "automation", "ci/cd", "pipeline", "workflow", "jenkins",
            "github actions", "webhook", "deploy", "build", "trigger",
            "script", "schedule", "devops", "自動化", "觸發", "排程"
        ],
        "boost_keywords": ["CI/CD", "Pipeline", "Trigger", "Deploy"],
    },
}

def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term)
    if re.fullmatch(r"[A-Za-z0-9]+", term) and len(term) <= 4:
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def _count_term_hits(text: str, term: str) -> int:
    if not text or not term:
        return 0
    return len(_term_pattern(term).findall(text))


def _category_for_doc(doc_name: str) -> Optional[str]:
    name_lower = (doc_name or "").lower()
    if any(k in name_lower for k in ["sit-tr-wl", "wifi", "wi-fi", "wireless", "ssid", "mesh", "router"]):
        return "WiFi"
    if any(k in name_lower for k in ["nr", "lte", "5g", "bear", "beam", "pdsch", "volte", "scell", "ca", "handover"]):
        return "4G/5G"
    if any(k in name_lower for k in ["wifi", "mesh", "ssid", "channel", "ap", "wpa", "router"]):
        return "WiFi"
    if any(k in name_lower for k in ["lab", "device", "equipment", "borrow", "calibration", "inventory"]):
        return "Lab"
    if any(k in name_lower for k in ["project", "pm", "onboarding", "milestone", "risk", "task"]):
        return "Project"
    if any(k in name_lower for k in ["auto", "ci/cd", "pipeline", "jenkins", "github", "workflow", "deploy"]):
        return "Automation"
    return None


def _category_from_storage_category(storage_category: str | None, extraction_mode: str | None = None) -> Optional[str]:
    value = (storage_category or extraction_mode or "").strip()
    if not value:
        return None

    normalized = value.lower().replace("-", "_").replace(" ", "")
    mapping = {
        "4g5g": "4G/5G",
        "4g_5g": "4G/5G",
        "4g/5g": "4G/5G",
        "report": "4G/5G",
        "simple": "4G/5G",
        "wifi": "WiFi",
        "lab": "Lab",
        "project": "Project",
        "automation": "Automation",
    }
    return mapping.get(normalized)


def _build_actual_file_categories() -> dict:
    """建立文件名稱到類別的對照表，以實際 metadata 與 processed 目錄為準。"""
    data_base = _load_data_base()
    processed_dir = data_base / "processed"
    category_to_folder = {
        "4G/5G": "4G_5G",
        "WiFi": "WiFi",
        "Lab": "Lab",
        "Project": "Project",
        "Automation": "Automation",
    }

    actual_file_categories = {}
    for meta_path in _iter_document_metadata_files(data_base):
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception:
            continue

        category = _category_from_storage_category(
            meta.get("storage_category"),
            meta.get("extraction_mode"),
        )
        if category not in category_to_folder:
            continue

        source_name = os.path.basename(str(meta.get("source_name") or ""))
        source_stem = str(meta.get("source_stem") or "").strip()
        original_path = str(meta.get("original_path") or "").strip()
        converted_path = str(meta.get("converted_path") or "").strip()
        for candidate in {
            source_name,
            source_stem,
            os.path.basename(original_path),
            os.path.basename(converted_path),
            Path(original_path).stem if original_path else "",
            Path(converted_path).stem if converted_path else "",
        }:
            candidate = str(candidate or "").strip()
            if candidate:
                actual_file_categories[candidate] = category

    for category, folder in category_to_folder.items():
        folder_path = processed_dir / folder
        if not folder_path.is_dir():
            continue
        for file_path in folder_path.iterdir():
            if file_path.suffix.lower() not in {".md", ".txt"}:
                continue
            actual_file_categories[file_path.name] = category
            actual_file_categories[file_path.stem] = category
    return actual_file_categories


def _resolve_source_category(doc_name: str, actual_file_categories: dict) -> Optional[str]:
    raw_name = Path(str(doc_name or "")).name
    stem = Path(raw_name).stem

    category = actual_file_categories.get(raw_name) or actual_file_categories.get(stem)
    if category in {"4G/5G", "WiFi", "Lab", "Project", "Automation"}:
        return category

    inferred = _category_for_doc(stem) or _category_for_doc(raw_name)
    if inferred in {"4G/5G", "WiFi", "Lab", "Project", "Automation"}:
        return inferred
    return None


def _score_category_query(query: str, profile: dict) -> float:
    score = 0.0
    query_lower = (query or "").lower()

    for keyword in profile.get("keywords", []):
        hits = _count_term_hits(query_lower, keyword.lower())
        if not hits:
            continue

        base = 12 if len(keyword) <= 4 else 8
        if keyword in profile.get("boost_keywords", []):
            base += 6

        score += base
        if hits > 1:
            score += min(hits - 1, 3) * 2

    for boost_keyword in profile.get("boost_keywords", []):
        hits = _count_term_hits(query, boost_keyword)
        if hits:
            score += 8 + min(hits - 1, 2) * 3

    return score


def _normalize_scores(scores: dict) -> dict:
    max_score = max(scores.values()) if scores else 0
    if max_score <= 0:
        return {k: 0 for k in CATEGORY_ORDER}
    return {
        category: int(round((value / max_score) * 100))
        for category, value in scores.items()
    }


def _resolve_openclaw_dir() -> Path:
    env_dir = os.environ.get("OPENCLAW_HOME")
    if env_dir:
        return Path(env_dir).expanduser()

    candidate = Path("/home/da40_ai_gb10/.openclaw")
    if candidate.exists():
        return candidate

    return Path.home() / ".openclaw"


def _is_compare_like_query(text: str) -> bool:
    return is_compare_like_query(text)


OPENCLAW_DIR = _resolve_openclaw_dir()
OPENCLAW_IDENTITY_DIR = OPENCLAW_DIR / "identity"
OPENCLAW_MEMORY_DIR = OPENCLAW_DIR / "workspace" / "memory"
DEFAULT_GATEWAY_HOST = os.environ.get("OPENCLAW_GATEWAY_HOST", "100.65.63.58")
REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL") or "redis://redis:6379/0"
CHAT_BROWSER_COOKIE = "kb_chat_browser_id"

CHAT_GLOBAL_CONCURRENCY_LIMIT = int(os.getenv("CHAT_GLOBAL_CONCURRENCY_LIMIT", "3"))
CHAT_BROWSER_CONCURRENCY_LIMIT = int(os.getenv("CHAT_BROWSER_CONCURRENCY_LIMIT", "1"))
CHAT_SESSION_LOCK_TTL = int(os.getenv("CHAT_SESSION_LOCK_TTL", "1200"))
CHAT_GLOBAL_SLOT_TTL = int(os.getenv("CHAT_GLOBAL_SLOT_TTL", "1200"))
CHAT_GLOBAL_SLOT_KEY = "kb:chat:global_slots"
CHAT_SESSION_LOCK_PREFIX = "kb:chat:session_lock:"
CHAT_QUEUE_KEY = "kb:chat:queue"
CHAT_QUEUE_SEQ_KEY = "kb:chat:queue:seq"
CHAT_QUEUE_ACTIVE_KEY = "kb:chat:queue:active"
CHAT_QUEUE_REQUEST_PREFIX = "kb:chat:queue:req:"
CHAT_QUEUE_SCHEDULER_LOCK_KEY = "kb:chat:queue:scheduler_lock"
CHAT_QUEUE_POLL_INTERVAL = float(os.getenv("CHAT_QUEUE_POLL_INTERVAL", "0.5"))
CHAT_QUEUE_QUEUE_TTL = int(os.getenv("CHAT_QUEUE_QUEUE_TTL", "1800"))
CHAT_QUEUE_ACTIVE_TTL = int(os.getenv("CHAT_QUEUE_ACTIVE_TTL", str(CHAT_SESSION_LOCK_TTL)))


def _upload_file_sort_key(file_path: Path) -> tuple[int, str]:
    """以修改時間排序，並用路徑做次序穩定化。"""
    try:
        mtime_ns = file_path.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = 0
    return (mtime_ns, str(file_path))


def _delete_upload_artifacts(raw_dir: Path, processed_dir: Path, raw_file: Path) -> None:
    """刪除 raw 檔與其對應的 processed 成果。"""
    relative_path = raw_file.relative_to(raw_dir)
    processed_base = processed_dir / relative_path

    targets = [
        raw_file,
        processed_base.with_suffix(".md"),
        processed_base.with_suffix(".source.json"),
    ]

    for target in targets:
        try:
            if target.exists():
                target.unlink()
                logger.info("已刪除舊檔: %s", target)
        except Exception as exc:
            logger.warning("刪除舊檔失敗: %s - %s", target, exc)


def _enforce_upload_retention(limit: int = UPLOAD_RETENTION_LIMIT) -> dict:
    """
    只保留最新的 `limit` 個上傳檔案。

    以 raw 檔修改時間為準，超出的檔案會連同對應的 processed 檔一起刪除。
    """
    raw_dir = Path("data/raw")
    processed_dir = Path("data/processed")

    if not raw_dir.exists():
        return {"kept": 0, "removed": 0, "removed_files": []}

    raw_files = [f for f in raw_dir.rglob("*") if f.is_file()]
    raw_files.sort(key=_upload_file_sort_key, reverse=True)

    if len(raw_files) <= limit:
        return {"kept": len(raw_files), "removed": 0, "removed_files": []}

    removed_files = raw_files[limit:]
    for raw_file in removed_files:
        _delete_upload_artifacts(raw_dir, processed_dir, raw_file)

    return {
        "kept": len(raw_files[:limit]),
        "removed": len(removed_files),
        "removed_files": [str(f.relative_to(raw_dir)) for f in removed_files],
    }


def _read_json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"無法讀取設定檔: {path}") from exc


def _pem_body(pem: str) -> str:
    return "".join(
        line.strip()
        for line in (pem or "").splitlines()
        if line and not line.startswith("-----")
    )


def _pem_public_key_raw(pem: str) -> str:
    body = _pem_body(pem)
    if not body:
        return ""
    raw = base64.b64decode(body)
    return base64.urlsafe_b64encode(raw[-32:]).decode("ascii").rstrip("=")


def _load_chat_session_key() -> str:
    override = os.environ.get("OPENCLAW_CHAT_SESSION_KEY")
    if override:
        return override.strip()

    patterns = [
        r"Dashboard session:\s*`([^`]+)`",
        r"正式 Chat 網址:\s*`([^`]+)`",
        r"session key[:：]\s*`([^`]+)`",
        r"sessionKey[:：]\s*`([^`]+)`",
    ]

    if OPENCLAW_MEMORY_DIR.exists():
        memory_files = sorted(OPENCLAW_MEMORY_DIR.glob("*.md"), reverse=True)
        for memory_file in memory_files:
            try:
                content = memory_file.read_text(encoding="utf-8")
            except Exception:
                continue
            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    return match.group(1).strip()

    raise RuntimeError("找不到 OpenClaw chat session key，請更新 ~/.openclaw/workspace/memory/*.md")


def load_openclaw_chat_config() -> dict:
    device_path = OPENCLAW_IDENTITY_DIR / "device.json"
    auth_path = OPENCLAW_IDENTITY_DIR / "device-auth.json"
    openclaw_path = OPENCLAW_DIR / "openclaw.json"

    device = _read_json_file(device_path)
    device_auth = _read_json_file(auth_path)
    openclaw = _read_json_file(openclaw_path)

    gateway_config = openclaw.get("gateway", {})
    gateway_port = int(os.environ.get("OPENCLAW_GATEWAY_PORT") or gateway_config.get("port", 18789))
    gateway_host = os.environ.get("OPENCLAW_GATEWAY_HOST", DEFAULT_GATEWAY_HOST)
    gateway_ws_url = os.environ.get("OPENCLAW_GATEWAY_WS_URL") or f"ws://{gateway_host}:{gateway_port}/ws"

    operator_token = device_auth.get("tokens", {}).get("operator", {})
    scopes = operator_token.get("scopes") or [
        "operator.admin",
        "operator.approvals",
        "operator.pairing",
        "operator.read",
        "operator.talk.secrets",
        "operator.write",
    ]

    return {
        "sessionKey": _load_chat_session_key(),
        "gatewayWsUrl": gateway_ws_url,
        "gatewayHttpUrl": gateway_ws_url.replace("ws://", "http://", 1).replace("wss://", "https://", 1),
        "browserWsUrl": "/ws",
        "deviceId": device.get("deviceId", ""),
        "deviceToken": operator_token.get("token", ""),
        "authToken": (openclaw.get("gateway", {}).get("auth", {}) or {}).get("token", ""),
        "privateKeyPem": device.get("privateKeyPem", ""),
        "publicKeyPem": device.get("publicKeyPem", ""),
        "publicKeyRaw": _pem_public_key_raw(device.get("publicKeyPem", "")),
        "scopes": scopes,
        "client": {
            "id": "cli",
            "version": "1.0.0",
            "platform": "linux",
            "mode": "cli",
        },
        "locale": "zh-TW",
        "userAgent": "openclaw-web/1.0.0",
        "gatewayPort": gateway_port,
        "gatewayHost": gateway_host,
    }


def _get_or_create_chat_browser_id(cookie_value: str | None) -> str:
    value = (cookie_value or "").strip()
    if value:
        return value
    return uuid.uuid4().hex


def _resolve_browser_session_key(session_key: str, browser_id: str | None) -> str:
    value = _normalize_proxy_session_key(session_key)
    browser = (browser_id or "").strip()
    if "__browser__" in value or not browser:
        return value
    return f"{value}__browser__{browser}"


def _canonical_chat_session_key(session_key: str | None) -> str:
    value = (session_key or "").strip()
    if not value:
        return ""
    if value.startswith("agent:"):
        parts = value.split(":", 2)
        if len(parts) == 3 and parts[2].strip():
            return parts[2].strip()
    return value


def _get_redis_client():
    import redis

    return redis.from_url(REDIS_URL)


def _chat_session_lock_key(session_key: str) -> str:
    return f"{CHAT_SESSION_LOCK_PREFIX}{session_key}"


def _chat_session_token(session_key: str) -> str:
    digest = hashlib.sha256(session_key.encode("utf-8")).hexdigest()
    return digest


def _acquire_chat_session_lock(r, session_key: str, ttl: int = CHAT_SESSION_LOCK_TTL) -> bool:
    return bool(r.set(_chat_session_lock_key(session_key), _chat_session_token(session_key), nx=True, ex=ttl))


def _refresh_chat_session_lock(r, session_key: str, ttl: int = CHAT_SESSION_LOCK_TTL) -> None:
    lock_key = _chat_session_lock_key(session_key)
    if r.get(lock_key) == _chat_session_token(session_key):
        r.expire(lock_key, ttl)


def _release_chat_session_lock(r, session_key: str) -> None:
    lock_key = _chat_session_lock_key(session_key)
    token = _chat_session_token(session_key)
    script = """
    local key = KEYS[1]
    local token = ARGV[1]
    if redis.call('GET', key) == token then
      return redis.call('DEL', key)
    end
    return 0
    """
    try:
        r.eval(script, 1, lock_key, token)
    except Exception as exc:
        logger.warning("釋放 session lock 失敗: %s", exc)


def _acquire_global_chat_slot(r, slot_member: str, ttl: int = CHAT_GLOBAL_SLOT_TTL, limit: int = CHAT_GLOBAL_CONCURRENCY_LIMIT) -> bool:
    script = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local ttl = tonumber(ARGV[2])
    local limit = tonumber(ARGV[3])
    local member = ARGV[4]
    redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
    local count = redis.call('ZCARD', key)
    if count >= limit then
      return 0
    end
    redis.call('ZADD', key, now + ttl, member)
    redis.call('EXPIRE', key, ttl)
    return 1
    """
    try:
        result = r.eval(script, 1, CHAT_GLOBAL_SLOT_KEY, int(datetime.now().timestamp()), ttl, limit, slot_member)
        return bool(result)
    except Exception as exc:
        logger.warning("取得全域聊天槽失敗: %s", exc)
        return False


def _refresh_global_chat_slot(r, slot_member: str, ttl: int = CHAT_GLOBAL_SLOT_TTL) -> None:
    script = """
    local key = KEYS[1]
    local now = tonumber(ARGV[1])
    local ttl = tonumber(ARGV[2])
    local member = ARGV[3]
    if redis.call('ZSCORE', key, member) then
      redis.call('ZADD', key, now + ttl, member)
      redis.call('EXPIRE', key, ttl)
      return 1
    end
    return 0
    """
    try:
        r.eval(script, 1, CHAT_GLOBAL_SLOT_KEY, int(datetime.now().timestamp()), ttl, slot_member)
    except Exception as exc:
        logger.warning("刷新全域聊天槽失敗: %s", exc)


def _release_global_chat_slot(r, slot_member: str) -> None:
    try:
        r.zrem(CHAT_GLOBAL_SLOT_KEY, slot_member)
    except Exception as exc:
        logger.warning("釋放全域聊天槽失敗: %s", exc)


def _normalize_proxy_session_key(session_key: str | None) -> str:
    value = (session_key or "").strip()
    if not value:
        raise ValueError("缺少 sessionKey")
    return value


def _chat_queue_request_key(request_id: str) -> str:
    return f"{CHAT_QUEUE_REQUEST_PREFIX}{request_id}"


def _chat_browser_active_key(browser_id: str) -> str:
    return f"kb:chat:browser_active:{browser_id}"


def _decode_redis_hash(meta: dict) -> dict[str, str]:
    decoded: dict[str, str] = {}
    for key, value in (meta or {}).items():
        if isinstance(key, bytes):
            key = key.decode("utf-8", errors="ignore")
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="ignore")
        decoded[str(key)] = str(value)
    return decoded


def _browser_active_count(r, browser_id: str) -> int:
    try:
        value = r.get(_chat_browser_active_key(browser_id))
    except Exception:
        return 0
    if value is None:
        return 0
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    try:
        return max(0, int(value))
    except Exception:
        return 0


def _increment_browser_active_count(r, browser_id: str) -> None:
    key = _chat_browser_active_key(browser_id)
    try:
        count = int(r.incr(key))
    except Exception:
        count = 1
        r.set(key, count)
    if count < 1:
        r.set(key, 1)
        count = 1
    r.expire(key, CHAT_QUEUE_ACTIVE_TTL)


def _decrement_browser_active_count(r, browser_id: str) -> None:
    key = _chat_browser_active_key(browser_id)
    try:
        count = int(r.get(key) or 0)
    except Exception:
        count = 0
    if count <= 1:
        r.delete(key)
    else:
        r.decr(key)
        r.expire(key, CHAT_QUEUE_ACTIVE_TTL)


def _queue_request_browser_id(r, request_id: str) -> str:
    meta = _decode_redis_hash(r.hgetall(_chat_queue_request_key(request_id)) or {})
    browser_id = meta.get("browser_id")
    return str(browser_id or "")


def _queue_request_status(r, request_id: str) -> str:
    meta = _decode_redis_hash(r.hgetall(_chat_queue_request_key(request_id)) or {})
    status = meta.get("status", "")
    return str(status or "")


def _queue_request_position(r, request_id: str) -> int | None:
    try:
        rank = r.zrank(CHAT_QUEUE_KEY, request_id)
        return None if rank is None else int(rank) + 1
    except Exception as exc:
        logger.warning("取得排隊位置失敗: %s", exc)
        return None


def _cleanup_chat_queue_state(r) -> None:
    now = int(datetime.now().timestamp())
    try:
        expired_request_ids = r.zrangebyscore(CHAT_QUEUE_ACTIVE_KEY, "-inf", now - 1)
    except Exception as exc:
        logger.warning("清理聊天 active 狀態失敗: %s", exc)
        return

    for request_id in expired_request_ids:
        if isinstance(request_id, bytes):
            request_id = request_id.decode("utf-8", errors="ignore")
        request_key = _chat_queue_request_key(str(request_id))
        try:
            meta = _decode_redis_hash(r.hgetall(request_key) or {})
            browser_id = meta.get("browser_id", "")
            if browser_id:
                _decrement_browser_active_count(r, str(browser_id))
            r.zrem(CHAT_QUEUE_ACTIVE_KEY, str(request_id))
            r.delete(request_key)
        except Exception as exc:
            logger.warning("清理過期聊天請求失敗: %s", exc)


def _enqueue_chat_request(r, request_id: str, browser_id: str, session_key: str, message: str) -> int:
    now = int(datetime.now().timestamp())
    queue_seq = int(r.incr(CHAT_QUEUE_SEQ_KEY))
    request_key = _chat_queue_request_key(request_id)
    r.hset(
        request_key,
        mapping={
            "request_id": request_id,
            "browser_id": browser_id,
            "session_key": session_key,
            "message": message,
            "status": "queued",
            "enqueued_at": now,
            "queue_seq": queue_seq,
        },
    )
    r.expire(request_key, CHAT_QUEUE_QUEUE_TTL)
    r.zadd(CHAT_QUEUE_KEY, {request_id: queue_seq})
    r.expire(CHAT_QUEUE_KEY, CHAT_QUEUE_QUEUE_TTL)
    logger.info(
        "Chat queue enqueue request_id=%s browser_id=%s session_key=%s queue_seq=%s",
        request_id,
        browser_id,
        session_key,
        queue_seq,
    )
    return queue_seq


def _release_chat_queue_request(r, request_id: str) -> None:
    try:
        request_key = _chat_queue_request_key(request_id)
        browser_id = r.hget(request_key, "browser_id")
        if isinstance(browser_id, bytes):
            browser_id = browser_id.decode("utf-8", errors="ignore")
        status = r.hget(request_key, "status")
        if isinstance(status, bytes):
            status = status.decode("utf-8", errors="ignore")
        if browser_id and (status == "active" or r.zscore(CHAT_QUEUE_ACTIVE_KEY, request_id) is not None):
            _decrement_browser_active_count(r, str(browser_id))
        r.zrem(CHAT_QUEUE_ACTIVE_KEY, request_id)
        r.zrem(CHAT_QUEUE_KEY, request_id)
        r.delete(request_key)
        logger.info(
            "Chat queue release request_id=%s browser_id=%s status=%s",
            request_id,
            browser_id,
            status,
        )
    except Exception as exc:
        logger.warning("釋放聊天請求失敗: %s", exc)


def _try_claim_chat_request(r, request_id: str) -> dict:
    """
    讓排在最前且符合公平配額的請求進入執行中。

    回傳:
      - {"state": "granted"}
      - {"state": "waiting", "queue_position": int | None}
      - {"state": "missing"}
    """
    now = int(datetime.now().timestamp())
    _cleanup_chat_queue_state(r)

    request_key = _chat_queue_request_key(request_id)
    meta = _decode_redis_hash(r.hgetall(request_key) or {})
    if not meta:
        logger.info("Chat queue claim missing request_id=%s", request_id)
        return {"state": "missing"}

    status = meta.get("status", "")
    if status == "active":
        logger.info("Chat queue claim already active request_id=%s", request_id)
        return {"state": "granted"}
    if status != "queued":
        logger.info("Chat queue claim invalid status request_id=%s status=%s", request_id, status)
        return {"state": "missing"}

    queue_rank = r.zrank(CHAT_QUEUE_KEY, request_id)
    if queue_rank is None:
        logger.info("Chat queue claim missing rank request_id=%s", request_id)
        return {"state": "missing"}

    active_count = r.zcard(CHAT_QUEUE_ACTIVE_KEY)
    if active_count >= CHAT_GLOBAL_CONCURRENCY_LIMIT:
        logger.info(
            "Chat queue claim waiting global limit request_id=%s queue_rank=%s active_count=%s",
            request_id,
            queue_rank,
            active_count,
        )
        return {"state": "waiting", "queue_position": int(queue_rank) + 1}

    queue_members = r.zrange(CHAT_QUEUE_KEY, 0, -1)
    for raw_member in queue_members:
        member = raw_member.decode("utf-8", errors="ignore") if isinstance(raw_member, bytes) else str(raw_member)
        member_key = _chat_queue_request_key(member)
        member_meta = _decode_redis_hash(r.hgetall(member_key) or {})
        if not member_meta:
            r.zrem(CHAT_QUEUE_KEY, member)
            continue

        member_status = member_meta.get("status", "")
        if member_status != "queued":
            continue

        member_browser_id = member_meta.get("browser_id", "")
        if not member_browser_id:
            continue

        browser_active_count = _browser_active_count(r, str(member_browser_id))
        if browser_active_count >= CHAT_BROWSER_CONCURRENCY_LIMIT:
            logger.info(
                "Chat queue claim waiting browser limit request_id=%s member=%s browser_id=%s browser_active_count=%s",
                request_id,
                member,
                member_browser_id,
                browser_active_count,
            )
            continue

        if member != request_id:
            logger.info(
                "Chat queue claim waiting ahead request_id=%s ahead_of=%s queue_rank=%s",
                request_id,
                member,
                r.zrank(CHAT_QUEUE_KEY, request_id),
            )
            return {
                "state": "waiting",
                "queue_position": int(r.zrank(CHAT_QUEUE_KEY, request_id) or 0) + 1,
            }

        if r.zcard(CHAT_QUEUE_ACTIVE_KEY) >= CHAT_GLOBAL_CONCURRENCY_LIMIT:
            logger.info(
                "Chat queue claim waiting active count recheck request_id=%s queue_rank=%s",
                request_id,
                queue_rank,
            )
            return {"state": "waiting", "queue_position": int(queue_rank) + 1}

        member_session_key = member_meta.get("session_key", "")
        if member_session_key and not _acquire_chat_session_lock(r, str(member_session_key)):
            logger.info(
                "Chat queue claim waiting session lock request_id=%s session_key=%s",
                request_id,
                member_session_key,
            )
            return {"state": "waiting", "queue_position": int(queue_rank) + 1}

        r.zrem(CHAT_QUEUE_KEY, request_id)
        r.zadd(CHAT_QUEUE_ACTIVE_KEY, {request_id: now + CHAT_QUEUE_ACTIVE_TTL})
        r.hset(
            request_key,
            mapping={
                "status": "active",
                "started_at": now,
            },
        )
        r.expire(request_key, CHAT_QUEUE_QUEUE_TTL)
        _increment_browser_active_count(r, str(member_browser_id))
        logger.info(
            "Chat queue claim granted request_id=%s browser_id=%s session_key=%s active_count=%s",
            request_id,
            member_browser_id,
            member_session_key,
            r.zcard(CHAT_QUEUE_ACTIVE_KEY),
        )
        return {"state": "granted"}

    return {"state": "waiting", "queue_position": int(queue_rank) + 1}


def _is_terminal_chat_message(message: dict) -> bool:
    if not isinstance(message, dict):
        return False

    if message.get("type") == "res" and message.get("id") and not message.get("ok", True):
        return True

    if message.get("type") == "event" and message.get("event") == "chat":
        payload = message.get("payload") or {}
        state = payload.get("state")
        return state in {"final", "failed", "end"}

    if message.get("type") == "event" and message.get("event") == "lifecycle":
        payload = message.get("payload") or {}
        return payload.get("phase") == "end"

    return False


# ===== Log Emitter (Server-Sent Events) =====

class LogEmitter:
    """記憶日誌，用於 SSE 推播"""
    _instance: Optional['LogEmitter'] = None
    _logs: deque
    _max_logs: int = 500
    
    def __init__(self):
        self._logs = deque(maxlen=self._max_logs)
    
    @classmethod
    def get_instance(cls) -> 'LogEmitter':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def add_log(self, level: str, message: str, source: str = "system"):
        """新增日誌"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = {
            "timestamp": timestamp,
            "level": level,
            "message": message,
            "source": source
        }
        self._logs.append(log_entry)
    
    def get_logs(self, limit: int = 100) -> List[dict]:
        """取得最近的日誌"""
        return list(self._logs)[-limit:]
    
    def clear(self):
        """清除所有日誌"""
        self._logs.clear()


# 全域日誌發射器
log_emitter = LogEmitter.get_instance()


# 包装 logger.addHandler 來捕獲日誌
class LogCapture(logging.Handler):
    """自定義日誌處理器，將日誌傳送到 LogEmitter"""
    def emit(self, record):
        try:
            msg = self.format(record)
            level = record.levelname
            source = record.name
            log_emitter.add_log(level, msg, source)
        except Exception:
            self.handleError(record)


# 設定日誌捕獲
log_capture = LogCapture()
log_capture.setFormatter(logging.Formatter('%(message)s'))
logging.getLogger().addHandler(log_capture)


# ===== Lifespan =====

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("FastAPI 啟動")
    
    # 初始化 Celery Beat 排程
    try:
        from .tasks import get_beat_schedule_config, update_celery_beat
        config = get_beat_schedule_config()
        if config.get("enabled"):
            update_celery_beat(config.get("interval_minutes", 5))
            logger.info(f"Celery Beat 已初始化: 每 {config.get('interval_minutes')} 分鐘")
    except Exception as e:
        logger.warning(f"Celery Beat 初始化失敗: {e}")
    
    yield
    logger.info("FastAPI 關閉")


# ===== FastAPI App =====

app = FastAPI(
    title="知識庫搜尋系統",
    description="GraphRAG + RAG 雙模式搜尋，支援多人同時使用",
    version="1.0.0",
    lifespan=lifespan
)

from .report_routes import router as report_router
app.include_router(report_router)
from .e2e_cleanup_routes import router as e2e_cleanup_router
app.include_router(e2e_cleanup_router)

# CORS 允許前端跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== API Endpoints =====

@app.get("/")
async def root():
    return {"message": "知識庫搜尋系統 API", "version": "1.0.0"}


@app.get("/health")
async def health_check():
    """健康檢查"""
    return {"status": "healthy"}


@app.get("/api/openclaw/chat-config")
async def get_openclaw_chat_config(request: Request, response: Response):
    """提供聊天室所需的 OpenClaw runtime 設定。"""
    try:
        browser_id = _get_or_create_chat_browser_id(request.cookies.get(CHAT_BROWSER_COOKIE))
        response.set_cookie(
            key=CHAT_BROWSER_COOKIE,
            value=browser_id,
            max_age=60 * 60 * 24 * 365,
            httponly=False,
            secure=True,
            samesite="lax",
            path="/",
        )
        return load_openclaw_chat_config()
    except Exception as exc:
        logger.exception("載入 OpenClaw chat 設定失敗")
        raise HTTPException(status_code=500, detail=str(exc))


@app.websocket("/ws")
async def websocket_chat_proxy(websocket: WebSocket):
    """
    代理 browser chat websocket 到外部 gateway，並在此層做 session / concurrency 控制。
    """
    browser_id = _get_or_create_chat_browser_id(websocket.cookies.get(CHAT_BROWSER_COOKIE))
    proxy_conn_id = uuid.uuid4().hex[:8]
    await websocket.accept()
    redis_client = _get_redis_client()
    browser_send_lock = asyncio.Lock()
    session_key: str | None = None
    active_request_id: str | None = None
    current_queue_position: int | None = None
    session_lock_acquired = False
    upstream = None
    browser_task = None
    upstream_task = None
    pending_request_ids: set[str] = set()

    async def send_to_browser(payload: dict):
        async with browser_send_lock:
            await websocket.send_json(payload)

    async def release_current_request():
        nonlocal session_key, active_request_id, current_queue_position, session_lock_acquired
        if session_key and session_lock_acquired:
            await asyncio.to_thread(_release_chat_session_lock, redis_client, session_key)
            session_lock_acquired = False
        if active_request_id:
            await asyncio.to_thread(_release_chat_queue_request, redis_client, active_request_id)
            pending_request_ids.discard(active_request_id)
            active_request_id = None
        current_queue_position = None

    async def release_pending_requests():
        pending_ids = list(pending_request_ids)
        pending_request_ids.clear()
        for request_id in pending_ids:
            await asyncio.to_thread(_release_chat_queue_request, redis_client, request_id)

    async def run_compare_report_graph_direct(message_text: str, top_k: int = 12) -> Optional[dict]:
        """
        直接跑比較題的 KB 路徑，先讓 WiFi compare 命中 WiFi 路由，
        再讓一般 compare / report_graph 作為第二順位，避免前端或 proxy 先被 report_graph 截胡。
        """
        if not _is_compare_like_query(message_text):
            return None

        try:
            result = await asyncio.to_thread(_run_compare_report_graph_via_local_api, message_text, top_k)
        except Exception as exc:
            logger.error("run_compare_report_graph_direct failed: %s", exc)
            return None

        if not isinstance(result, dict):
            return None
        if result.get("mode") not in {"wifi_compare", "report_graph"}:
            return None
        if not str(result.get("answer") or "").strip():
            return None
        return result

    def _run_compare_report_graph_via_local_api(message_text: str, top_k: int = 12) -> Optional[dict]:
        """
        透過本機 /search API 取回與前端一致的 report_graph 結果。
        這樣可避免 proxy 進程直接碰 Neo4j 時的環境差異。
        """
        payload = {
            "query": message_text,
            "mode": "auto",
            "top_k": top_k,
            "sources_only": True,
        }
        request = urllib.request.Request(
            "http://127.0.0.1:8000/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            search_data = json.loads(response.read().decode("utf-8"))

        task_id = search_data.get("task_id")
        if not task_id:
            return None

        deadline = time.time() + 120
        while time.time() < deadline:
            with urllib.request.urlopen(f"http://127.0.0.1:8000/tasks/{task_id}", timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
            if result.get("status") in {"completed", "failed", "error"}:
                return result
            time.sleep(1)

        return None

    try:
        logger.info("WebSocket proxy[%s] accepted browser_id=%s", proxy_conn_id, browser_id)
        chat_config = load_openclaw_chat_config()
        gateway_ws_url = chat_config.get("gatewayWsUrl")
        if not gateway_ws_url:
            logger.warning("WebSocket proxy[%s] missing gateway_ws_url browser_id=%s", proxy_conn_id, browser_id)
            await send_to_browser({"error": "找不到 gateway websocket 設定"})
            await websocket.close(code=1011)
            return

        import websockets

        try:
            upstream = await websockets.connect(
                gateway_ws_url,
                ping_interval=30,
                ping_timeout=30,
                max_queue=32,
            )
            logger.info("WebSocket proxy[%s] connected upstream browser_id=%s gateway=%s", proxy_conn_id, browser_id, gateway_ws_url)
        except Exception as exc:
            logger.error("WebSocket proxy[%s] 連接 gateway websocket 失敗 browser_id=%s: %s", proxy_conn_id, browser_id, exc)
            await send_to_browser({"error": "聊天服務暫時無法連線"})
            await websocket.close(code=1011)
            return

        async def browser_to_upstream():
            nonlocal session_key, active_request_id, current_queue_position, session_lock_acquired
            logger.info("WebSocket proxy[%s] browser task started browser_id=%s", proxy_conn_id, browser_id)
            while True:
                try:
                    raw_text = await websocket.receive_text()
                except WebSocketDisconnect as exc:
                    logger.info("WebSocket proxy[%s] browser task disconnect browser_id=%s: %s", proxy_conn_id, browser_id, exc)
                    raise
                except Exception as exc:
                    logger.info("WebSocket proxy[%s] browser task error browser_id=%s: %s", proxy_conn_id, browser_id, exc)
                    raise
                try:
                    message = json.loads(raw_text)
                except Exception:
                    await upstream.send(raw_text)
                    continue

                if message.get("type") == "auth":
                    expected_auth_token = chat_config.get("authToken", "")
                    received_token = message.get("token", "")
                    if expected_auth_token and received_token != expected_auth_token:
                        await send_to_browser({"error": "授權失敗"})
                        await websocket.close(code=4401)
                        return
                    logger.info("WebSocket auth accepted for browser_id=%s", browser_id)
                    await upstream.send(raw_text)
                    continue

                if message.get("type") == "req":
                    method = message.get("method")
                    params = message.get("params") if isinstance(message.get("params"), dict) else {}
                    logger.info("WebSocket browser req method=%s id=%s browser_id=%s", method, message.get("id"), browser_id)

                    if method == "chat.history":
                        session_key = _resolve_browser_session_key(params.get("sessionKey") or message.get("sessionKey"), browser_id)
                        params["sessionKey"] = session_key
                        message["params"] = params
                        logger.info("WebSocket forwarding chat.history id=%s", message.get("id"))
                        await upstream.send(json.dumps(message, ensure_ascii=False))
                        continue

                    if method == "chat.send":
                        session_key = _resolve_browser_session_key(params.get("sessionKey") or message.get("sessionKey"), browser_id)
                        params["sessionKey"] = session_key
                        message["params"] = params
                        request_id = str(message.get("id") or f"chat-{uuid.uuid4().hex}")
                        message["id"] = request_id
                        current_queue_position = None
                        missing_retry_count = 0
                        pending_request_ids.add(request_id)

                        await asyncio.to_thread(
                            _enqueue_chat_request,
                            redis_client,
                            request_id,
                            browser_id,
                            session_key,
                            params.get("message", ""),
                        )
                        queue_position = await asyncio.to_thread(
                            _queue_request_position,
                            redis_client,
                            request_id,
                        )
                        if queue_position is not None:
                            current_queue_position = queue_position
                            await send_to_browser({
                                "type": "event",
                                "event": "chat.queue",
                                "payload": {
                                    "requestId": request_id,
                                    "queuePosition": queue_position,
                                    "estimatedWaitSeconds": max(0, (queue_position - 1) * 10),
                                },
                            })
                        await send_to_browser({
                            "type": "res",
                            "id": request_id,
                            "ok": True,
                            "payload": {
                                "status": "queued",
                                "queue_position": queue_position,
                                "estimated_wait_seconds": max(0, (queue_position - 1) * 10) if queue_position else None,
                            },
                        })

                        while True:
                            claim = await asyncio.to_thread(
                                _try_claim_chat_request,
                                redis_client,
                                request_id,
                            )
                            if claim.get("state") == "granted":
                                active_request_id = request_id
                                session_lock_acquired = True
                                current_queue_position = None
                                pending_request_ids.discard(request_id)
                                logger.info("WebSocket chat request granted request_id=%s session_key=%s", request_id, session_key)
                                compare_result = await run_compare_report_graph_direct(params.get("message", ""))
                                if compare_result is not None:
                                    logger.info("WebSocket compare shortcut applied request_id=%s", request_id)
                                    await send_to_browser({
                                        "type": "res",
                                        "id": request_id,
                                        "ok": True,
                                        "content": compare_result.get("answer", ""),
                                    })
                                    await release_current_request()
                                    break
                                logger.info("WebSocket forwarding chat.send upstream request_id=%s", request_id)
                                await upstream.send(json.dumps(message, ensure_ascii=False))
                                break
                            if claim.get("state") == "missing":
                                missing_retry_count += 1
                                if missing_retry_count > 3:
                                    await asyncio.to_thread(_release_chat_queue_request, redis_client, request_id)
                                    active_request_id = None
                                    pending_request_ids.discard(request_id)
                                    await send_to_browser({
                                        "type": "res",
                                        "id": request_id,
                                        "ok": False,
                                        "error": {"message": "排隊中的請求已失效，請重新送出。"},
                                    })
                                    break

                                await asyncio.to_thread(
                                    _enqueue_chat_request,
                                    redis_client,
                                    request_id,
                                    browser_id,
                                    session_key,
                                    params.get("message", ""),
                                )
                                queue_position = await asyncio.to_thread(
                                    _queue_request_position,
                                    redis_client,
                                    request_id,
                                )
                                if queue_position is not None:
                                    current_queue_position = queue_position
                                    await send_to_browser({
                                        "type": "event",
                                        "event": "chat.queue",
                                        "payload": {
                                            "requestId": request_id,
                                            "queuePosition": queue_position,
                                            "estimatedWaitSeconds": max(0, (queue_position - 1) * 10),
                                        },
                                    })
                                await asyncio.sleep(CHAT_QUEUE_POLL_INTERVAL)
                                continue

                            queue_position = claim.get("queue_position")
                            if queue_position is not None and queue_position != current_queue_position:
                                current_queue_position = queue_position
                                await send_to_browser({
                                    "type": "event",
                                    "event": "chat.queue",
                                    "payload": {
                                        "requestId": request_id,
                                        "queuePosition": queue_position,
                                        "estimatedWaitSeconds": max(0, (queue_position - 1) * 10),
                                    },
                                })

                            await asyncio.sleep(CHAT_QUEUE_POLL_INTERVAL)
                        continue

                    logger.info("WebSocket forwarding req method=%s id=%s to upstream", method, message.get("id"))
                    await upstream.send(json.dumps(message, ensure_ascii=False))
                    continue

                if message.get("type") == "chat.history":
                    session_key = _resolve_browser_session_key(message.get("sessionKey"), browser_id)
                    logger.info("WebSocket bare chat.history browser_id=%s session_key=%s", browser_id, session_key)
                    request_id = str(message.get("id") or f"history-{uuid.uuid4().hex}")
                    normalized_message = {
                        "type": "req",
                        "id": request_id,
                        "method": "chat.history",
                        "params": {
                            **{
                                key: value
                                for key, value in message.items()
                                if key not in {"type", "id", "sessionKey"}
                            },
                            "sessionKey": session_key,
                        },
                    }
                    logger.info("WebSocket forwarding bare chat.history id=%s", request_id)
                    await upstream.send(json.dumps(normalized_message, ensure_ascii=False))
                    continue

                if message.get("type") == "chat.send":
                    session_key = _resolve_browser_session_key(message.get("sessionKey"), browser_id)
                    request_id = str(message.get("id") or f"chat-{uuid.uuid4().hex}")
                    pending_request_ids.add(request_id)
                    normalized_message = {
                        "type": "req",
                        "id": request_id,
                        "method": "chat.send",
                        "params": {
                            **{
                                key: value
                                for key, value in message.items()
                                if key not in {"type", "id", "sessionKey"}
                            },
                            "sessionKey": session_key,
                        },
                    }
                    current_queue_position = None
                    missing_retry_count = 0

                    await asyncio.to_thread(
                        _enqueue_chat_request,
                        redis_client,
                        request_id,
                        browser_id,
                        session_key,
                        normalized_message.get("params", {}).get("message", ""),
                    )
                    queue_position = await asyncio.to_thread(
                        _queue_request_position,
                        redis_client,
                        request_id,
                    )
                    if queue_position is not None:
                        current_queue_position = queue_position
                        await send_to_browser({
                            "type": "event",
                            "event": "chat.queue",
                            "payload": {
                                "requestId": request_id,
                                "queuePosition": queue_position,
                                "estimatedWaitSeconds": max(0, (queue_position - 1) * 10),
                            },
                        })
                    await send_to_browser({
                        "type": "res",
                        "id": request_id,
                        "ok": True,
                        "payload": {
                            "status": "queued",
                            "queue_position": queue_position,
                            "estimated_wait_seconds": max(0, (queue_position - 1) * 10) if queue_position else None,
                        },
                    })

                    while True:
                        claim = await asyncio.to_thread(
                            _try_claim_chat_request,
                            redis_client,
                            request_id,
                        )
                        if claim.get("state") == "granted":
                            active_request_id = request_id
                            session_lock_acquired = True
                            current_queue_position = None
                            pending_request_ids.discard(request_id)
                            logger.info("WebSocket bare chat request granted request_id=%s session_key=%s", request_id, session_key)
                            compare_result = await run_compare_report_graph_direct(normalized_message.get("params", {}).get("message", ""))
                            if compare_result is not None:
                                logger.info("WebSocket bare compare shortcut applied request_id=%s", request_id)
                                await send_to_browser({
                                    "type": "res",
                                    "id": request_id,
                                    "ok": True,
                                    "content": compare_result.get("answer", ""),
                                })
                                await release_current_request()
                                break
                            logger.info("WebSocket forwarding bare chat.send upstream request_id=%s", request_id)
                            await upstream.send(json.dumps(normalized_message, ensure_ascii=False))
                            break
                        if claim.get("state") == "missing":
                            missing_retry_count += 1
                            if missing_retry_count > 3:
                                await asyncio.to_thread(_release_chat_queue_request, redis_client, request_id)
                                active_request_id = None
                                pending_request_ids.discard(request_id)
                                await send_to_browser({
                                    "type": "res",
                                    "id": request_id,
                                    "ok": False,
                                    "error": {"message": "排隊中的請求已失效，請重新送出。"},
                                })
                                break

                            await asyncio.to_thread(
                                _enqueue_chat_request,
                                redis_client,
                                request_id,
                                browser_id,
                                session_key,
                                normalized_message.get("params", {}).get("message", ""),
                            )
                            queue_position = await asyncio.to_thread(
                                _queue_request_position,
                                redis_client,
                                request_id,
                            )
                            if queue_position is not None:
                                current_queue_position = queue_position
                                await send_to_browser({
                                    "type": "event",
                                    "event": "chat.queue",
                                    "payload": {
                                        "requestId": request_id,
                                        "queuePosition": queue_position,
                                        "estimatedWaitSeconds": max(0, (queue_position - 1) * 10),
                                    },
                                })
                            await asyncio.sleep(CHAT_QUEUE_POLL_INTERVAL)
                            continue

                        queue_position = claim.get("queue_position")
                        if queue_position is not None and queue_position != current_queue_position:
                            current_queue_position = queue_position
                            await send_to_browser({
                                "type": "event",
                                "event": "chat.queue",
                                "payload": {
                                    "requestId": request_id,
                                    "queuePosition": queue_position,
                                    "estimatedWaitSeconds": max(0, (queue_position - 1) * 10),
                                },
                            })

                        await asyncio.sleep(CHAT_QUEUE_POLL_INTERVAL)
                    continue

                if session_key and session_lock_acquired:
                    await asyncio.to_thread(_refresh_chat_session_lock, redis_client, session_key)
                await upstream.send(json.dumps(message, ensure_ascii=False))
            logger.info("WebSocket proxy[%s] browser task finished browser_id=%s", proxy_conn_id, browser_id)

        async def upstream_to_browser():
            nonlocal session_key, active_request_id, session_lock_acquired
            logger.info("WebSocket proxy[%s] upstream task started browser_id=%s", proxy_conn_id, browser_id)
            while True:
                try:
                    raw_message = await upstream.recv()
                except Exception as exc:
                    logger.info("WebSocket proxy[%s] upstream task recv ended browser_id=%s: %s", proxy_conn_id, browser_id, exc)
                    raise
                logger.info("WebSocket upstream raw message len=%s", len(raw_message) if raw_message is not None else 0)
                try:
                    payload = json.loads(raw_message)
                except Exception:
                    payload = None
                if isinstance(payload, dict):
                    logger.info(
                        "WebSocket upstream payload type=%s event=%s id=%s ok=%s",
                        payload.get("type"),
                        payload.get("event"),
                        payload.get("id"),
                        payload.get("ok"),
                    )

                if isinstance(payload, dict) and payload.get("event") == "chat":
                    chat_payload = payload.get("payload") or {}
                    message_payload = chat_payload.get("message") or {}
                    message_meta = message_payload.get("meta") if isinstance(message_payload, dict) else {}
                    event_session_key = (
                        chat_payload.get("sessionKey")
                        if isinstance(chat_payload, dict) else None
                    ) or (
                        chat_payload.get("session_key")
                        if isinstance(chat_payload, dict) else None
                    ) or (
                        message_payload.get("sessionKey")
                        if isinstance(message_payload, dict) else None
                    ) or (
                        message_payload.get("session_key")
                        if isinstance(message_payload, dict) else None
                    ) or (
                        message_meta.get("sessionKey")
                        if isinstance(message_meta, dict) else None
                    ) or (
                        message_meta.get("session_key")
                        if isinstance(message_meta, dict) else None
                    )
                    logger.info(
                        "WebSocket chat event keys=%s payload_keys=%s message_keys=%s session_candidates=%s",
                        list(payload.keys()),
                        list(chat_payload.keys()) if isinstance(chat_payload, dict) else [],
                        list(message_payload.keys()) if isinstance(message_payload, dict) else [],
                        {
                            "payload.sessionKey": chat_payload.get("sessionKey") if isinstance(chat_payload, dict) else None,
                            "payload.session_key": chat_payload.get("session_key") if isinstance(chat_payload, dict) else None,
                            "message.sessionKey": message_payload.get("sessionKey") if isinstance(message_payload, dict) else None,
                            "message.session_key": message_payload.get("session_key") if isinstance(message_payload, dict) else None,
                            "message.meta.sessionKey": message_meta.get("sessionKey") if isinstance(message_meta, dict) else None,
                            "message.meta.session_key": message_meta.get("session_key") if isinstance(message_meta, dict) else None,
                        },
                    )

                    normalized_event_session_key = _canonical_chat_session_key(event_session_key)
                    normalized_current_session_key = _canonical_chat_session_key(session_key)

                    if normalized_current_session_key and normalized_event_session_key and normalized_event_session_key != normalized_current_session_key:
                        logger.info(
                            "Skip chat event for mismatched session: event=%s current=%s",
                            normalized_event_session_key,
                            normalized_current_session_key,
                        )
                        continue

                    if normalized_current_session_key and isinstance(chat_payload, dict) and not event_session_key:
                        chat_payload["sessionKey"] = normalized_current_session_key
                        payload["payload"] = chat_payload
                    elif normalized_current_session_key and isinstance(chat_payload, dict) and event_session_key != normalized_current_session_key:
                        chat_payload["sessionKey"] = normalized_current_session_key
                        payload["payload"] = chat_payload

                await send_to_browser(payload if isinstance(payload, dict) else {"type": "raw", "data": raw_message})

                if session_key and session_lock_acquired:
                    await asyncio.to_thread(_refresh_chat_session_lock, redis_client, session_key)

                if payload and _is_terminal_chat_message(payload):
                    await release_current_request()
            logger.info("WebSocket proxy[%s] upstream task finished browser_id=%s", proxy_conn_id, browser_id)

        browser_task = asyncio.create_task(browser_to_upstream(), name=f"browser_to_upstream[{proxy_conn_id}]")
        upstream_task = asyncio.create_task(upstream_to_browser(), name=f"upstream_to_browser[{proxy_conn_id}]")

        done, pending = await asyncio.wait(
            {browser_task, upstream_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        logger.info(
            "WebSocket proxy[%s] task completed browser_id=%s done=%s pending=%s",
            proxy_conn_id,
            browser_id,
            [task.get_name() for task in done],
            [task.get_name() for task in pending],
        )

        for task in pending:
            task.cancel()

        for task in done:
            with suppress(Exception):
                await task

    except WebSocketDisconnect:
        logger.info("WebSocket proxy[%s] browser disconnected browser_id=%s", proxy_conn_id, browser_id)
        pass
    except Exception as exc:
        logger.exception("WebSocket proxy[%s] chat proxy 發生錯誤 browser_id=%s: %s", proxy_conn_id, browser_id, exc)
        with suppress(Exception):
            await send_to_browser({"error": "聊天代理發生錯誤"})
    finally:
        logger.info("WebSocket proxy[%s] teardown browser_id=%s session_key=%s active_request_id=%s", proxy_conn_id, browser_id, session_key, active_request_id)
        if upstream is not None:
            with suppress(Exception):
                await upstream.close()
        with suppress(Exception):
            await release_pending_requests()
        with suppress(Exception):
            await release_current_request()
        with suppress(Exception):
            await websocket.close()


@app.post("/search", response_model=SearchResponse)
async def search(request: SearchRequest, background_tasks: BackgroundTasks, response: Response, http_request: Request):
    """
    提交搜尋任務

    - 第一次查詢：任務加入 Celery 佇列
    - 重複查詢：直接從 Redis 快取回傳（1小時有效期）
    """
    # 檢查快取
    filters = request.filters.model_dump(exclude_none=True) if request.filters else {}
    filters_key = json.dumps(filters, sort_keys=True, ensure_ascii=False)
    cache_key = f"search:{request.query}:{request.mode}:{request.top_k if request.top_k is not None else 'default'}:{filters_key}"
    cached = cache_get(cache_key)

    if cached:
        logger.info(f"快取命中: {request.query[:50]}...")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return SearchResponse(
            task_id="cached",
            status="completed",
            message="從快取回傳"
        )

    # 提交 Celery 任務
    task = search_task.apply_async(
        args=[request.query, request.mode],
        kwargs={
            "user_id": request.user_id,
            "top_k": request.top_k,
            "sources_only": request.sources_only,
            "filters": filters,
        },
        headers=celery_headers(http_request.headers.get("x-trace-id")),
    )

    logger.info(f"任務已提交: {task.id}")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return SearchResponse(
        task_id=task.id,
        status="submitted",
        message="任務已提交，請使用 /tasks/{task_id} 查詢結果"
    )


def _knowledge_lifecycle():
    from ..knowledge_lifecycle import KnowledgeLifecycle
    return KnowledgeLifecycle()


def _require_knowledge_lifecycle_enabled():
    if os.getenv("KB_KNOWLEDGE_LIFECYCLE_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="knowledge lifecycle is disabled")


@app.post("/api/v1/knowledge/revisions")
async def register_knowledge_revision(request: KnowledgeRevisionRequest):
    """Register a revision before it becomes searchable."""
    _require_knowledge_lifecycle_enabled()
    try:
        return {"data": _knowledge_lifecycle().register(request.model_dump()), "error": None}
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/v1/knowledge/revisions/{package_id}")
async def get_knowledge_revision(package_id: str):
    _require_knowledge_lifecycle_enabled()
    revision = _knowledge_lifecycle().get(package_id)
    if not revision:
        raise HTTPException(status_code=404, detail="knowledge revision not found")
    return {"data": revision, "error": None}


@app.post("/api/v1/knowledge/revisions/{package_id}/transition")
async def transition_knowledge_revision(package_id: str, request: KnowledgeRevisionTransition):
    _require_knowledge_lifecycle_enabled()
    lifecycle = _knowledge_lifecycle()
    try:
        if request.target == "published":
            from ..knowledge_graph_lifecycle import KnowledgeGraphLifecycle
            from ..vector_store import VectorStore
            graph = KnowledgeGraphLifecycle()
            try:
                item = lifecycle.publish(package_id, vector_store=VectorStore(), graph_writer=graph)
            finally:
                graph.close()
        else:
            item = lifecycle.transition(package_id, request.target)
        return {"data": item, "error": None}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="knowledge revision not found") from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str, response: Response):
    """查詢任務狀態與結果"""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    # 從 Redis 檢查快取
    cache_key = f"result:{task_id}"
    cached = cache_get(cache_key)

    if cached:
        return TaskStatusResponse(
            task_id=task_id,
            status="completed",
            answer=cached.get("answer"),
            sources=cached.get("sources"),
            citation_distribution=cached.get("citation_distribution"),
            mode=cached.get("mode")
        )

    # 檢查 Celery 任務狀態
    task_result = AsyncResult(task_id)

    if task_result.ready():
        result = task_result.result
        if isinstance(result, dict):
            # 寫入快取
            cache_set(cache_key, result, ttl=3600)
            return TaskStatusResponse(
                task_id=task_id,
                status="completed",
                answer=result.get("answer"),
                sources=result.get("sources"),
                citation_distribution=result.get("citation_distribution"),
                mode=result.get("mode")
            )
        else:
            return TaskStatusResponse(
                task_id=task_id,
                status="failed",
                error=str(result)
            )
    elif task_result.state == 'PENDING':
        # 任務還在排隊中，計算排隊位置
        try:
            inspect = Inspect('memory://')
            stats = inspect.stats() or {}
            
            # 取得 active tasks 數量
            active = inspect.active() or {}
            active_count = sum(len(tasks) for tasks in active.values())
            
            # 估算排隊位置（簡化版：active tasks 數量）
            queue_position = active_count
            estimated_wait = active_count * 10  # 每個任務約 10 秒
            
            return TaskStatusResponse(
                task_id=task_id,
                status="pending",
                queue_position=queue_position,
                estimated_wait_seconds=estimated_wait
            )
        except Exception:
            return TaskStatusResponse(
                task_id=task_id,
                status="pending"
            )
    else:
        return TaskStatusResponse(
            task_id=task_id,
            status=task_result.state.lower()
        )


@app.delete("/tasks/{task_id}")
async def cancel_task(task_id: str):
    """取消任務"""
    task_result = AsyncResult(task_id)
    task_result.revoke()

    return {"message": f"任務 {task_id} 已取消"}




@app.post("/category-relevance", response_model=CategoryRelevanceResponse)
async def get_category_relevance(request: CategoryRelevanceRequest):
    """
    取得問題與各類別的關聯程度
    
    - 根據問題向量化搜尋
    - 統計各類別的相關文件數量
    - 回傳強/中/弱/無狀態
    """
    from ..vector_store import VectorStore
    
    vs = VectorStore()
    results = vs.search(request.query, top_k=request.top_k)
    
    # Category mapping
    def get_category(doc_name):
        name_lower = doc_name.lower()
        if any(k in name_lower for k in ['nr', 'lte', '5g', 'bear', 'beam', 'pdsch', 'volte', 'scell', 'ca']):
            return '4G/5G'
        elif any(k in name_lower for k in ['wifi', 'mesh', 'ap', 'channel', 'iot']):
            return 'WiFi'
        elif any(k in name_lower for k in ['lab', 'device', 'equipment']):
            return 'Lab'
        elif any(k in name_lower for k in ['project', 'pm', 'onboarding']):
            return 'Project'
        elif any(k in name_lower for k in ['auto', 'ci/cd', 'pipeline', 'jenkins', 'github']):
            return 'Automation'
        return 'Unknown'
    
    # Count by category
    category_counts = {'4G/5G': 0, 'WiFi': 0, 'Lab': 0, 'Project': 0, 'Automation': 0}
    for r in results:
        cat = get_category(r['doc_name'])
        if cat in category_counts:
            category_counts[cat] += 1
    
    return CategoryRelevanceResponse(
        query=request.query,
        categories=category_counts
    )


@app.post("/api/source-categories", response_model=SourceCategoryResponse)
async def get_source_categories(request: SourceCategoryRequest):
    """依實際 processed 內容與文件名稱，解析來源文件所屬類別。"""
    actual_file_categories = _build_actual_file_categories()
    category_counts = {"4G/5G": 0, "WiFi": 0, "Lab": 0, "Project": 0, "Automation": 0}
    source_categories = {}
    matched_count = 0
    unmatched_count = 0

    for source_name in request.sources or []:
        category = _resolve_source_category(source_name, actual_file_categories)
        source_categories[source_name] = category
        if category in category_counts:
            category_counts[category] += 1
            matched_count += 1
        else:
            unmatched_count += 1

    return SourceCategoryResponse(
        categories=category_counts,
        source_categories=source_categories,
        matched_count=matched_count,
        unmatched_count=unmatched_count,
    )


@app.post("/analyze-question", response_model=AnalyzeQuestionResponse)
async def analyze_question(request: AnalyzeQuestionRequest):
    """
    分析問題與類別關聯，回傳卡片盒可用的權重資料。

    流程：
    1. LLM 提取問題中的關鍵實體
    2. 查詢 Neo4j / 向量庫找出相關文件
    3. 依照查詢關鍵字與命中文件進行加權
    4. 回傳原始分數與 0-100 正規化分數
    """
    from ..vector_store import VectorStore
    from neo4j import GraphDatabase
    from ..main import load_config

    config = load_config()
    neo4j_config = config.get("neo4j", {})
    llm_config = config.get("ollama", {})
    from .ollama_client import OllamaClient
    llm = OllamaClient(
        model=llm_config.get("model", "qwen3-coder-next"),
        base_url=llm_config.get("instances", ["http://localhost:11434"])[0] if llm_config.get("instances") else llm_config.get("base_url", "http://localhost:11434")
    )
    
    # Step 1: LLM 提取實體
    entity_prompt = f"""你是一個專業的知識庫助理。請從以下問題中提取關鍵實體名詞。

問題：{request.query}

請列出所有與電信網路、設備、協定、技術相關的實體名詞（用繁體中文或英文皆可）。

只輸出實體名稱，用逗號分隔，不要有其他解釋。

範例輸出：LTE,handover,A3 event,PCI"""

    try:
        entity_response = llm.chat([
            {"role": "user", "content": entity_prompt}
        ])
        entities_text = entity_response.strip()
        
        # 解析實體（用逗號分隔）
        entities = [e.strip() for e in entities_text.split(',') if e.strip()]
        logger.info(f"[AnalyzeQuestion] Extracted entities: {entities}")
    except Exception as e:
        logger.error(f"[AnalyzeQuestion] LLM entity extraction failed: {e}")
        entities = []
    
    # Step 2: 連線 Neo4j 查詢相關文件
    try:
        driver = GraphDatabase.driver(
            neo4j_config["uri"],
            auth=(neo4j_config["user"], neo4j_config["password"])
        )
        
        with driver.session() as session:
            # 查詢與實體相關的文件
            # 假設 Document 節點有 name 屬性，Entity 節點有 name 屬性
            # 它們之間有 RELATES_TO 或 MENTIONS 關係
            
            cypher = """
            MATCH (d:Document)-[:RELATES_TO|MENTIONS*1..2]->(e:Entity)
            WHERE e.name IN $entities
            WITH d, count(e) as relevance_score
            RETURN d.name as doc_name, relevance_score
            ORDER BY relevance_score DESC
            LIMIT 30
            """
            
            result = session.run(cypher, entities=entities)
            doc_scores = [(record["doc_name"], record["relevance_score"]) for record in result]
        
        driver.close()
        logger.info(f"[AnalyzeQuestion] Found {len(doc_scores)} related docs from Neo4j")
        
    except Exception as e:
        logger.error(f"[AnalyzeQuestion] Neo4j query failed: {e}")
        doc_scores = []

    # 如果 Neo4j 找不到，改用向量搜尋
    if not doc_scores:
        logger.info("[AnalyzeQuestion] Falling back to vector search")
        vs = VectorStore()
        results = vs.search(request.query, top_k=20)
        doc_scores = [(r['doc_name'], r.get('score', 0)) for r in results]
    
    # Step 3: 建立實際檔案資料夾對照表（用於驗證檔案是否真的在該類別）
    import os
    processed_dir = "/home/da40_ai_gb10/knowledge-base/data/processed"
    category_to_folder = {
        '4G/5G': '4G_5G',
        'WiFi': 'WiFi',
        'Lab': 'Lab',
        'Project': 'Project',
        'Automation': 'Automation'
    }
    
    # 建立：檔案名稱 → 實際類別 的對照表
    actual_file_categories = {}  # {"filename.md": "4G/5G", ...}
    for category, folder in category_to_folder.items():
        folder_path = os.path.join(processed_dir, folder)
        if os.path.isdir(folder_path):
            for f in os.listdir(folder_path):
                if f.endswith('.md'):
                    actual_file_categories[f] = category
                    # 也加入不含 .md 的版本
                    actual_file_categories[f.replace('.md', '')] = category

    logger.info(f"[AnalyzeQuestion] Actual file categories: {len(actual_file_categories)} files")
    # Step 4: 將文件分類並做加權
    def resolve_category(doc_name):
        if doc_name in actual_file_categories:
            return actual_file_categories[doc_name]
        if (doc_name + ".md") in actual_file_categories:
            return actual_file_categories[doc_name + ".md"]
        return _category_for_doc(doc_name)

    def dedupe_preserve_order(file_list):
        seen = set()
        result = []
        for item in file_list:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    raw_scores = {category: 0.0 for category in CATEGORY_ORDER}
    related_docs = {category: [] for category in CATEGORY_ORDER}

    # 4-1. 查詢字串權重：參考 C# 機制，關鍵字命中與 boost term 命中都加權
    query_score_total = 0.0
    for category, profile in CATEGORY_WEIGHT_PROFILES.items():
        score = _score_category_query(request.query, profile)
        raw_scores[category] += score
        query_score_total += score

    # 4-2. 文件命中權重：越前面的命中、分數越高的文件，貢獻越大
    for rank, (doc_name, relevance_score) in enumerate(doc_scores):
        category = resolve_category(doc_name)
        if category not in raw_scores:
            continue

        related_docs[category].append(doc_name)

        if relevance_score is None:
            doc_weight = 0.0
        elif relevance_score > 1:
            doc_weight = min(24.0, float(relevance_score) * 4.0)
        else:
            doc_weight = min(20.0, float(relevance_score) * 25.0)

        rank_weight = max(0.0, 12.0 - (rank * 1.5))
        raw_scores[category] += doc_weight + rank_weight

    # 4-3. 以實體命中補強相對分類
    entity_text = " ".join(entities).lower()
    if entity_text:
        for category, profile in CATEGORY_WEIGHT_PROFILES.items():
            for keyword in profile.get("keywords", []):
                if _count_term_hits(entity_text, keyword.lower()):
                    raw_scores[category] += 3.0

    # 4-4. 若文件名稱本身已能辨識類別，額外補一點穩定性
    for category, docs in related_docs.items():
        if docs:
            raw_scores[category] += min(len(docs), 5) * 2.0

    # 4-5. 清理並正規化
    for category in related_docs:
        related_docs[category] = dedupe_preserve_order(related_docs[category])

    normalized_scores = _normalize_scores(raw_scores)
    top_category = max(raw_scores, key=raw_scores.get) if raw_scores else None
    top_score = round(raw_scores.get(top_category, 0.0), 2) if top_category else 0.0
    total_score = sum(raw_scores.values())
    confidence = round((top_score / total_score) * 100, 2) if total_score > 0 else 0.0

    logger.info(f"[AnalyzeQuestion] Query boost scores: {query_score_total:.2f}")
    logger.info(f"[AnalyzeQuestion] Category scores: {raw_scores}")
    logger.info(f"[AnalyzeQuestion] Normalized scores: {normalized_scores}")
    logger.info(f"[AnalyzeQuestion] Related docs: {related_docs}")

    estimated_wait_seconds = None
    try:
        from .tasks import celery_app
        inspect = celery_app.control.inspect()
        active = inspect.active() or {}
        active_count = sum(len(items) for items in active.values())
        estimated_wait_seconds = active_count * 8
    except Exception:
        estimated_wait_seconds = None

    return AnalyzeQuestionResponse(
        query=request.query,
        category_scores={k: round(v, 2) for k, v in raw_scores.items()},
        normalized_scores=normalized_scores,
        related_docs=related_docs,
        top_category=top_category,
        top_score=top_score,
        confidence=confidence,
        analysis_method="weighted_query_and_document_scoring",
        estimated_wait_seconds=estimated_wait_seconds,
    )
@app.get("/stats")
async def get_stats():
    """系統統計資訊"""
    from .tasks import celery_app

    inspect = celery_app.control.inspect()
    stats = inspect.stats() or {}

    return {
        "active_workers": len(stats),
        "queued_tasks": len(inspect.active() or {}),
        "cache_enabled": True
    }


# ===== System Heartbeat Endpoint =====

@app.get("/admin/stats")
@app.get("/api/admin/stats")
async def get_system_stats():
    """系統狀態心跳端點，供前端燈號偵測使用"""
    try:
        from .tasks import celery_app
        from neo4j import GraphDatabase
        from ..main import load_config
        from datetime import datetime
        
        # 檢查 Celery workers 數量
        inspect = celery_app.control.inspect()
        stats = inspect.stats() or {}
        active_workers = len(stats)
        
        # 嘗試連線 Neo4j
        neo4j_ok = False
        try:
            config = load_config()
            neo4j_config = config.get("neo4j", {})
            driver = GraphDatabase.driver(
                neo4j_config.get("uri", "bolt://neo4j:7687"),
                auth=(
                    neo4j_config.get("user", "neo4j"),
                    neo4j_config.get("password") or os.getenv("NEO4J_PASSWORD", ""),
                ),
            )
            with driver.session() as session:
                session.run('MATCH (n) RETURN count(n) as cnt limit 1')
            driver.close()
            neo4j_ok = True
        except:
            pass
        
        return {
            "status": "ok" if neo4j_ok else "degraded",
            "active_workers": active_workers,
            "neo4j": "connected" if neo4j_ok else "disconnected",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {
            "status": "error",
            "active_workers": 0,
            "neo4j": "unknown",
            "timestamp": datetime.now().isoformat()
        }


# ===== Admin Endpoints =====

@app.get("/admin/graph-stats")
async def admin_graph_stats():
    """取得 Neo4j 圖譜統計"""
    from fastapi.responses import JSONResponse
    from ..graphrag.neo4j_schema import get_graph_stats
    from ..ingest import load_config as ingest_load_config, _get_neo4j_connection_info

    config = ingest_load_config()
    neo4j_config = config.get("neo4j", {})
    neo4j_uri, neo4j_user, neo4j_password = _get_neo4j_connection_info(config)
    stats = get_graph_stats(
        neo4j_uri,
        neo4j_user,
        neo4j_password,
    )
    return JSONResponse(content={
        "status": "ok" if stats else "error",
        "uri": neo4j_uri,
        "user": neo4j_user,
        "database": neo4j_config.get("database", "neo4j"),
        "nodes": stats.get("nodes", {}),
        "relationships": stats.get("relationships", {}),
    })


@app.get("/admin/vector-stats")
async def admin_vector_stats():
    """取得 QDrant 向量資料庫統計"""
    try:
        from ..vector_store import get_vector_store
        vs = get_vector_store()
        return vs.get_stats()
    except Exception as e:
        logger.error(f"取得 QDrant 統計失敗: {e}")
        return {"error": str(e)}


@app.get("/admin/chunk-documents")
async def admin_chunk_documents():
    """列出可供 Chunk Viewer 瀏覽的文件。"""
    try:
        from ..vector_store import get_vector_store
        vs = get_vector_store()
        return {
            "documents": vs.list_documents(),
        }
    except Exception as e:
        logger.error(f"取得 chunk 文件清單失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/chunk-documents/{doc_name}/chunks")
async def admin_chunk_document_chunks(doc_name: str):
    """取得指定文件的所有 chunk 與原圖引用。"""
    try:
        from ..vector_store import get_vector_store
        vs = get_vector_store()
        return {
            "doc_name": doc_name,
            "chunks": vs.list_chunks(doc_name),
        }
    except Exception as e:
        logger.error(f"取得 chunk 明細失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/chunk-documents/{doc_name}/versions")
async def admin_chunk_document_versions(doc_name: str):
    """取得指定文件的編輯版本歷史。"""
    try:
        from ..chunk_editing import list_chunk_versions
        return {
            "doc_name": doc_name,
            "versions": list_chunk_versions(doc_name),
        }
    except Exception as e:
        logger.error(f"取得 chunk 版本失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/chunk-documents/{doc_name}/chunks/{chunk_id}/edit")
async def admin_chunk_document_edit_chunk(doc_name: str, chunk_id: str, payload: ChunkEditRequest):
    """修改 chunk 文字，保存為來源檔並重新 ingest。"""
    try:
        from ..vector_store import get_vector_store
        from ..chunk_editing import (
            apply_chunk_edit_to_source,
            create_chunk_version_backup,
            rebuild_source_excel_assets,
        )
        from ..ingest import ingest_document, detect_extraction_mode

        vs = get_vector_store()
        chunks = vs.list_chunks(doc_name)
        chunk = next((item for item in chunks if str(item.get("id")) == str(chunk_id)), None)
        if not chunk:
            raise HTTPException(status_code=404, detail="找不到指定 chunk")

        source_path = str(chunk.get("source_path") or "").strip()
        if not source_path:
            docs = {doc.get("doc_name"): doc for doc in vs.list_documents()}
            source_path = str((docs.get(doc_name) or {}).get("source_path") or "").strip()
        if not source_path:
            raise HTTPException(status_code=404, detail="找不到可編輯的來源檔")

        source_file = Path(source_path)
        if not source_file.exists():
            raise HTTPException(status_code=404, detail=f"來源檔不存在: {source_path}")

        old_content = str(chunk.get("content") or "")
        new_content = (payload.content or "").rstrip("\n")
        current_text = source_file.read_text(encoding="utf-8")

        backup = create_chunk_version_backup(
            doc_name=doc_name,
            source_path=source_path,
            chunk_id=str(chunk_id),
            chunk_index=int(chunk.get("chunk_index") or 0),
            old_content=old_content,
            new_content=new_content,
        )

        updated_text, edit_strategy = apply_chunk_edit_to_source(
            current_text,
            old_content,
            new_content,
            section_title=str(chunk.get("section_title") or chunk.get("metadata", {}).get("header", "") or ""),
        )
        if edit_strategy == "unchanged":
            raise HTTPException(status_code=409, detail="來源檔內容與 chunk 不一致，請重新整理後再試")

        source_file.write_text(updated_text, encoding="utf-8")
        rebuild_source_excel_assets(source_path)

        extraction_mode = detect_extraction_mode(source_file.stem)
        ingested = ingest_document(
            str(source_file),
            enable_vector=True,
            extraction_mode=extraction_mode,
            preserve_assets=True,
        )

        return {
            "status": "success" if ingested else "failed",
            "doc_name": doc_name,
            "chunk_id": chunk_id,
            "source_path": source_path,
            "backup": backup,
            "ingested": ingested,
            "edit_strategy": edit_strategy,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"編輯 chunk 失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/chunk-documents/{doc_name}/versions/{version_id}/restore")
async def admin_chunk_document_restore_version(doc_name: str, version_id: str):
    """回復指定歷史版本並重新 ingest。"""
    try:
        from ..chunk_editing import (
            get_chunk_version,
            restore_chunk_version,
            create_chunk_version_backup,
            apply_chunk_edit_to_source,
            rebuild_source_excel_assets,
        )
        from ..ingest import ingest_document, detect_extraction_mode

        manifest = get_chunk_version(doc_name, version_id)
        source_path = str(manifest.get("source_path") or "").strip()
        if not source_path:
            raise HTTPException(status_code=404, detail="找不到版本對應的來源檔")

        source_file = Path(source_path)
        if not source_file.exists():
            raise HTTPException(status_code=404, detail=f"來源檔不存在: {source_path}")

        current_text = source_file.read_text(encoding="utf-8")
        create_chunk_version_backup(
            doc_name=doc_name,
            source_path=source_path,
            chunk_id=f"restore-{version_id}",
            chunk_index=int(manifest.get("chunk_index") or 0),
            old_content=current_text[:1000],
            new_content=(manifest.get("old_content_preview") or "")[:1000],
            reason="restore_before",
        )

        restore_chunk_version(doc_name, version_id)
        rebuild_source_excel_assets(source_path)
        extraction_mode = detect_extraction_mode(source_file.stem)
        ingested = ingest_document(
            str(source_file),
            enable_vector=True,
            extraction_mode=extraction_mode,
            preserve_assets=True,
        )
        return {
            "status": "success" if ingested else "failed",
            "doc_name": doc_name,
            "version_id": version_id,
            "source_path": source_path,
            "ingested": ingested,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"回復 chunk 版本失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/admin/chunk-assets/{asset_path:path}")
async def admin_chunk_assets(asset_path: str):
    """提供 chunk viewer 使用的資產檔案。"""
    try:
        from ..chunk_assets import ASSETS_ROOT

        normalized_asset_path = (asset_path or "").removeprefix("asset://").lstrip("/")
        requested = (ASSETS_ROOT / normalized_asset_path).resolve()
        assets_root = ASSETS_ROOT.resolve()
        if assets_root not in requested.parents and requested != assets_root:
            raise HTTPException(status_code=403, detail="非法的資產路徑")
        if not requested.exists() or not requested.is_file():
            raise HTTPException(status_code=404, detail="資產不存在")
        return FileResponse(str(requested))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"讀取 chunk 資產失敗: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/admin/schema/refresh")
async def admin_refresh_schema():
    """重新整理 Neo4j Schema"""
    from ..graphrag.neo4j_schema import setup_neo4j_schema, clear_all_data
    from ..ingest import load_config as ingest_load_config, _get_neo4j_connection_info

    config = ingest_load_config()
    neo4j_uri, neo4j_user, neo4j_password = _get_neo4j_connection_info(config)

    # 先清除再重建
    clear_all_data(
        neo4j_uri,
        neo4j_user,
        neo4j_password,
    )

    success = setup_neo4j_schema(
        neo4j_uri,
        neo4j_user,
        neo4j_password,
    )

    return {"status": "success" if success else "failed"}


@app.delete("/admin/cache")
async def admin_clear_cache():
    """清除所有快取"""
    from .cache import cache_clear_pattern

    count = cache_clear_pattern("*")
    return {"deleted": count}


@app.get("/admin/logs")
async def admin_get_logs(lines: int = 100):
    """取得系統日誌（從內存日誌）"""
    return {"logs": log_emitter.get_logs(limit=lines)}


@app.get("/admin/logs/stream")
async def admin_logs_stream():
    """SSE 日誌串流 endpoint"""
    async def event_generator():
        import asyncio
        last_count = len(log_emitter.get_logs())

        while True:
            # 檢查新日誌
            current_logs = log_emitter.get_logs()
            if len(current_logs) > last_count:
                # 有新日誌，發送所有日誌
                yield f"data: {json.dumps(current_logs, ensure_ascii=False)}\n\n"
                last_count = len(current_logs)

            # keepalive，避免反向代理長時間沒有資料而關閉 SSE 連線
            yield ": keepalive\n\n"
            await asyncio.sleep(2)  # 每 2 秒檢查一次

    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.delete("/admin/logs")
async def admin_clear_logs():
    """清除所有日誌"""
    log_emitter.clear()
    return {"status": "cleared"}


# ===== 檔案上傳與轉換 =====

class UploadRequest(BaseModel):
    file_name: str

class UploadResponse(BaseModel):
    status: str
    file_name: str
    converted_path: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None
    message: Optional[str] = None
    duplicate: Optional[bool] = None
    task_id: Optional[str] = None
    ingested: Optional[bool] = None
    queue_position: Optional[int] = None
    file_hash: Optional[str] = None
    extraction_mode: Optional[str] = None
    extraction_mode_name: Optional[str] = None


class JSONUploadRequest(BaseModel):
    name: str
    content: str  # base64 encoded
    size: int = 0


class JSONUploadResponse(BaseModel):
    status: str
    file_name: str
    message: Optional[str] = None
    error: Optional[str] = None


@app.post("/upload/json", response_model=JSONUploadResponse)
@app.post("/api/upload/json", response_model=JSONUploadResponse)
async def upload_json(request: JSONUploadRequest):
    """
    以 JSON 格式上傳檔案（n8n workflow 專用）
    """
    import base64
    from ..converter import FileConverter
    from pathlib import Path
    
    try:
        upload_dir = Path("data/raw")
        upload_dir.mkdir(parents=True, exist_ok=True)
        
        file_content = base64.b64decode(request.content)
        file_path = upload_dir / request.name
        file_path.write_bytes(file_content)
        
        logger.info(f"JSON 檔案上傳：{request.name}")
        
        converter = FileConverter()
        output_path = upload_dir / f"{file_path.stem}.md"
        
        try:
            result = converter.convert_file(str(file_path), str(output_path))
            
            if result.get("status") == "success":
                return JSONUploadResponse(
                    status="success",
                    file_name=request.name,
                    message="已上傳並轉換"
                )
            else:
                return JSONUploadResponse(
                    status="failed",
                    file_name=request.name,
                    error=result.get("error", "轉換失敗")
                )
        except Exception as e:
            return JSONUploadResponse(
                status="failed",
                file_name=request.name,
                error=str(e)
            )
    except Exception as e:
        logger.error(f"JSON 上傳失敗：{e}")
        return JSONUploadResponse(
            status="failed",
            file_name=request.name,
            error=str(e)
        )




UPLOAD_MAX_PART_SIZE = 200 * 1024 * 1024


def _extract_uploaded_file(form_data):
    """從 multipart form 中取出上傳檔案。"""
    file = form_data.get("file")
    if file is None:
        raise HTTPException(status_code=400, detail="缺少上傳檔案欄位 file")
    return file


@app.post("/upload", response_model=UploadResponse)
@app.post("/api/upload", response_model=UploadResponse)
async def upload_file(request: Request, background_tasks: BackgroundTasks):
    """
    上傳檔案並使用 MarkItDown 轉換為 Markdown
    
    支援格式：pdf, docx, xlsx, pptx, txt, md, html, csv, json, xml, epub, msg, 圖片等
    """
    try:
        from ..converter import FileConverter
        from pathlib import Path
        from ..ingest import detect_extraction_mode

        form = await request.form(
            max_files=10,
            max_fields=20,
            max_part_size=UPLOAD_MAX_PART_SIZE
        )
        file = _extract_uploaded_file(form)
        category_folder = resolve_storage_category(detect_extraction_mode(Path(file.filename).stem), file.filename)

        # 建立上傳目錄
        upload_dir = Path("data/raw") / category_folder
        upload_dir.mkdir(parents=True, exist_ok=True)

        # 儲存上傳檔案
        file_path = upload_dir / file.filename
        
        # 處理二進位上傳
        content = await file.read()
        file_path.write_bytes(content)
        
        logger.info(f"檔案上傳：{file.filename} -> {file_path}")

        # 轉換為 Markdown
        converter = FileConverter()
        
        # 根據副檔名決定輸出路徑
        output_dir = Path("data/processed") / category_folder
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{file_path.stem}.md"
        
        try:
            result = converter.convert_file(str(file_path), str(output_path))
            
            if result.get("status") == "success":
                # 讀取轉換後的 Markdown 內容
                markdown_content = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
                retention_result = _enforce_upload_retention()
                if retention_result["removed"]:
                    logger.info(
                        "上傳保留策略已執行: 保留 %s 個，刪除 %s 個舊檔",
                        retention_result["kept"],
                        retention_result["removed"],
                    )
                
                return UploadResponse(
                    status="success",
                    file_name=file.filename,
                    converted_path=str(output_path),
                    content=markdown_content[:5000] if markdown_content else ""  # 限制內容長度
                )
            else:
                return UploadResponse(
                    status="failed",
                    file_name=file.filename,
                    error=result.get("error", "轉換失敗")
                )
                
        except Exception as e:
            logger.error(f"轉換失敗：{e}")
            return UploadResponse(
                status="failed",
                file_name=file.filename,
                error=str(e)
            )

    except Exception as e:
        logger.error(f"上傳失敗：{e}")
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/upload/ingest")
@app.post("/api/upload/ingest")
async def upload_and_ingest(request: Request, extraction_mode: str = "4g5g"):
    """
    上傳檔案並提交背景攝入任務。

    此端點不再同步等待轉換/LLM/Neo4j/QDrant 完成；成功接收檔案後立即回傳 task_id，
    前端透過 /upload/tasks/{task_id} 輪詢進度。
    """

    from ..extract_entities import get_extraction_info
    from .tasks import (
        INGEST_UPLOAD_ROOT,
        create_ingest_task_id,
        set_ingest_task_state,
        get_ingest_queue_position,
        ingest_file_task,
        get_ingest_task_state,
        get_ingest_task_state_by_file_hash,
    )
    from ..ingest import detect_extraction_mode
    from ..ingest_conflict_protection import IngestContractError, validate_ingest_file
    from ..ingest_registry import IngestRegistry, IngestRegistryConflict
    import shutil

    allowed_upload_modes = {"4g5g", "wifi", "lab", "project", "automation"}

    staging_path = None
    try:
        form = await request.form(
            max_files=10,
            max_fields=20,
            max_part_size=UPLOAD_MAX_PART_SIZE
        )
        file = _extract_uploaded_file(form)
        agent_identity = None
        if os.getenv("KB_INGEST_REQUIRE_AGENT_AUTH", "false").lower() in {"1", "true", "yes"}:
            from ..test_reports.auth import authenticate_agent
            agent_identity = authenticate_agent(request)
        content = await file.read()
        file_name = Path(file.filename or "upload.bin").name
        file_hash = hashlib.sha256(content).hexdigest()
        filename_mode = detect_extraction_mode(Path(file.filename).stem)
        # 檔名若已明確指向特定類型，優先使用檔名判定結果，避免 UI 預設值覆蓋。
        # 只有檔名無法辨識時，才回退到前端傳入的 extraction_mode。
        effective_mode = filename_mode if filename_mode != "4g5g" else extraction_mode
        if effective_mode not in allowed_upload_modes:
            logger.warning(
                "upload/ingest 收到不支援的 extraction_mode=%s，回退為 4g5g",
                effective_mode,
            )
            effective_mode = "4g5g"
        mode_info = get_extraction_info(effective_mode)
        mode_name = mode_info.get("name", effective_mode)
        category_folder = resolve_storage_category(effective_mode, file_name)
        allow_legacy = os.getenv("KB_ALLOW_LEGACY_INGEST", "false").lower() in {"1", "true", "yes"}
        supplied_identity_headers = any(
            request.headers.get(name)
            for name in ("Idempotency-Key", "X-KB-Source-System", "X-KB-Environment-Id", "X-KB-Run-Id", "X-KB-Artifact-Type", "X-KB-Document-Id")
        )
        identity = None
        staging_dir = INGEST_UPLOAD_ROOT / ".staging"
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging_path = staging_dir / f"{uuid.uuid4().hex}_{file_name}"
        staging_path.write_bytes(content)
        try:
            identity = validate_ingest_file(
                path=staging_path,
                headers=request.headers,
                extraction_mode=effective_mode,
                original_file_name=file_name,
                require_contract=not (allow_legacy and not supplied_identity_headers),
            )
        except IngestContractError as contract_error:
            if contract_error.code != "legacy_upload":
                logger.warning(
                    "upload/ingest contract rejected: code=%s fields=%s file_name=%s extraction_mode=%s",
                    contract_error.code,
                    contract_error.fields,
                    file_name,
                    effective_mode,
                )
                staging_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=contract_error.status_code,
                    detail={"code": contract_error.code, "message": str(contract_error), "fields": contract_error.fields},
                )

        registry = IngestRegistry() if identity else None
        if identity:
            registry.record_event("ingest_received", document_id=identity.document_id, source_system=identity.source_system, environment_id=identity.environment_id, run_id=identity.run_id)
            registry.record_event("metadata_validated", document_id=identity.document_id, idempotency_key=identity.idempotency_key)
            registry.record_event("hash_validated", document_id=identity.document_id, ingest_file_hash=identity.ingest_file_hash)
            if agent_identity and agent_identity["environment"] != identity.source_system.lower():
                staging_path.unlink(missing_ok=True)
                raise HTTPException(status_code=403, detail={"code": "agent_source_mismatch", "message": "Agent environment 與 sourceSystem 不一致"})
            task_id = create_ingest_task_id()
            try:
                record, duplicate = registry.register(identity.as_dict(), task_id)
            except IngestRegistryConflict as conflict:
                staging_path.unlink(missing_ok=True)
                registry.record_event("conflict_rejected", **{
                    "document_id": identity.document_id,
                    "idempotency_key": identity.idempotency_key,
                    "code": conflict.code,
                })
                raise HTTPException(
                    status_code=409,
                    detail={"code": conflict.code, "message": str(conflict), "document_id": identity.document_id, "idempotency_key": identity.idempotency_key},
                )
            if duplicate:
                staging_path.unlink(missing_ok=True)
                existing_state = get_ingest_task_state(record["task_id"])
                registry.record_event("duplicate_detected", record["task_id"], document_id=identity.document_id, idempotency_key=identity.idempotency_key)
                return {
                    "status": (existing_state or {}).get("status", record.get("status", "submitted")),
                    "task_id": record["task_id"],
                    "file_name": record["original_file_name"],
                    "file_hash": record["ingest_file_hash"],
                    "document_id": record["document_id"],
                    "idempotency_key": record["idempotency_key"],
                    "duplicate": True,
                    "ingested": bool((existing_state or {}).get("ingested")),
                    "message": "相同 idempotency_key 已存在，沿用原攝入任務",
                }
        else:
            # 僅在明確允許 legacy upload 時保留舊的檔案 hash 去重行為。
            existing_state = get_ingest_task_state_by_file_hash(file_hash)
            task_id = create_ingest_task_id()
        if not identity and existing_state:
            existing_status = existing_state.get("status")
            existing_mode = str(existing_state.get("extraction_mode") or "").strip()
            mode_changed = bool(existing_mode and existing_mode != effective_mode)
            if existing_status == "completed" and not mode_changed:
                staging_path.unlink(missing_ok=True)
                logger.info(
                    f"偵測到重複攝入檔案，略過：{file.filename} "
                    f"(hash={file_hash[:12]}, task_id={existing_state.get('task_id')})"
                )
                return {
                    "status": "success",
                    "file_name": file_name,
                    "task_id": existing_state.get("task_id"),
                    "converted_path": existing_state.get("converted_path"),
                    "content": existing_state.get("content", ""),
                    "ingested": True,
                    "duplicate": True,
                    "file_hash": file_hash,
                    "extraction_mode": existing_state.get("extraction_mode", extraction_mode),
                    "extraction_mode_name": existing_state.get("extraction_mode_name", mode_name),
                    "message": "檔案內容已攝入，已略過重複提交",
                }
            if existing_status not in {"failed"} and not mode_changed:
                staging_path.unlink(missing_ok=True)
                queue_position = existing_state.get("queue_position")
                if not queue_position and existing_status == "queued":
                    queue_position = get_ingest_queue_position(existing_state.get("task_id"))
                logger.info(
                    f"偵測到相同檔案正在處理，沿用既有任務：{file.filename} "
                    f"(hash={file_hash[:12]}, task_id={existing_state.get('task_id')})"
                )
                return {
                    "status": "submitted",
                    "file_name": file.filename,
                    "task_id": existing_state.get("task_id"),
                    "ingested": False,
                    "duplicate": True,
                    "file_hash": file_hash,
                    "queue_position": queue_position or 0,
                    "extraction_mode": existing_state.get("extraction_mode", extraction_mode),
                    "extraction_mode_name": existing_state.get("extraction_mode_name", mode_name),
                    "message": "相同檔案已在處理中，請等待目前任務完成",
                }

        task_dir = INGEST_UPLOAD_ROOT / category_folder / task_id
        original_dir = task_dir / "original"
        converted_dir = task_dir / "converted"
        original_dir.mkdir(parents=True, exist_ok=True)
        converted_dir.mkdir(parents=True, exist_ok=True)

        original_path = original_dir / file_name
        converted_path = converted_dir / f"{Path(file_name).stem}.md"
        shutil.move(str(staging_path), str(original_path))

        created_at = datetime.now().isoformat(timespec="seconds")
        state = {
            "task_id": task_id,
            "file_name": file_name,
            "original_path": str(original_path),
            "converted_path": str(converted_path),
            "file_hash": file_hash,
            "storage_category": category_folder,
            "extraction_mode": effective_mode,
            "extraction_mode_name": mode_name,
            "status": "queued",
            "created_at": created_at,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "ingested": False,
            "content": "",
        }
        if identity:
            state.update(identity.as_dict())
            state["file_hash"] = identity.ingest_file_hash
            registry.record_event("task_created", task_id, document_id=identity.document_id, idempotency_key=identity.idempotency_key)
        set_ingest_task_state(task_id, state)
        try:
            async_result = ingest_file_task.apply_async(
                args=[task_id],
                queue="ingest",
                headers=celery_headers(request.headers.get("x-trace-id")),
            )
        except Exception:
            if registry:
                registry.update_status(task_id, "ingest_failed")
            raise
        state["celery_task_id"] = async_result.id
        set_ingest_task_state(task_id, state)
        queue_position = get_ingest_queue_position(task_id)

        logger.info(f"上傳已加入攝入佇列：{file_name} task_id={task_id} (萃取模式: {mode_name})")
        response = {
            "status": "submitted",
            "task_id": task_id,
            "file_name": file_name,
            "file_hash": file_hash,
            "storage_category": category_folder,
            "extraction_mode": effective_mode,
            "extraction_mode_name": mode_name,
            "queue_position": queue_position,
            "message": "已加入攝入佇列"
        }
        if identity:
            response.update({
                "document_id": identity.document_id,
                "idempotency_key": identity.idempotency_key,
                "duplicate": False,
            })
        return response

    except HTTPException:
        if staging_path:
            staging_path.unlink(missing_ok=True)
        raise
    except Exception as e:
        if staging_path:
            staging_path.unlink(missing_ok=True)
        logger.error(f"提交攝入任務失敗：{e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/upload/tasks/{task_id}")
@app.get("/api/upload/tasks/{task_id}")
async def get_upload_task(task_id: str):
    """查詢單一非同步攝入任務狀態。"""
    from .tasks import get_ingest_task_state, get_ingest_queue_position

    state = get_ingest_task_state(task_id)
    if not state:
        from ..ingest_registry import IngestRegistry
        record = IngestRegistry().find_by_task(task_id)
        if not record:
            raise HTTPException(status_code=404, detail="找不到攝入任務")
        state = {
            "task_id": task_id,
            "status": record.get("status", "unknown"),
            "file_name": record.get("original_file_name", ""),
            "document_id": record.get("document_id", ""),
            "idempotency_key": record.get("idempotency_key", ""),
            "source_system": record.get("source_system", ""),
            "environment_id": record.get("environment_id", ""),
            "project_id": record.get("project_id", ""),
            "run_id": record.get("run_id", ""),
            "artifact_type": record.get("artifact_type", ""),
            "ingested": record.get("status") == "completed",
        }
    if state.get("status") == "queued":
        state["queue_position"] = get_ingest_queue_position(task_id)
    else:
        state["queue_position"] = 0
    return state


@app.get("/upload/tasks")
@app.get("/api/upload/tasks")
async def list_upload_tasks():
    """列出目前與近期非同步攝入任務。"""
    from .tasks import summarise_ingest_tasks
    return summarise_ingest_tasks(limit=50)


@app.post("/upload/tasks/clear")
@app.post("/api/upload/tasks/clear")
async def clear_upload_task_history():
    """清除已完成或失敗的攝入任務歷史。"""
    from .tasks import clear_ingest_task_history

    result = clear_ingest_task_history()
    return {
        "status": "success",
        **result,
    }


@app.get("/extraction-modes")
async def list_extraction_modes():
    """列出可用的萃取模式"""
    from ..extract_entities import EXTRACTION_MODES
    
    modes = []
    for key, value in EXTRACTION_MODES.items():
        modes.append({
            "id": key,
            "name": value["name"],
            "description": value["description"]
        })
    
    return {"modes": modes}


@app.get("/hybrid-status")
async def get_hybrid_status():
    """
    取得 Hybrid 模式目前的活躍人數
    用於前端判斷是否顯示「忙碌，請稍候」
    """
    from .cache import get_hybrid_count
    
    current_count = get_hybrid_count()
    max_allowed = 3
    
    return {
        "current_count": current_count,
        "max_allowed": max_allowed,
        "is_busy": current_count >= max_allowed,
        "message": "目前忙碌，請稍候" if current_count >= max_allowed else "可以使用"
    }


class BeatScheduleResponse(BaseModel):
    enabled: bool
    interval_minutes: int
    watch_folder: str
    processed_folder: str


class BeatScheduleUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = None
    watch_folder: Optional[str] = None
@app.get("/admin/beat-schedule", response_model=BeatScheduleResponse)
async def get_beat_schedule():
    """取得 Celery Beat 排程設定"""
    from .tasks import get_beat_schedule_config
    config = get_beat_schedule_config()
    return BeatScheduleResponse(**config)


@app.post("/admin/beat-schedule")
async def update_beat_schedule(request: BeatScheduleUpdateRequest):
    """更新 Celery Beat 排程設定 (即時模式)"""
    from .tasks import update_beat_schedule_config, watch_folder_scan
    
    config = update_beat_schedule_config(
        enabled=request.enabled,
        interval_minutes=request.interval_minutes,
        watch_folder=request.watch_folder
    )
    
    # 如果啟用了排程，立即執行一次掃描
    if request.enabled:
        watch_folder_scan.apply_async()
        message = f"排程已啟用（每 {config.get('interval_minutes', 1)} 分鐘執行）"
    else:
        message = "排程已停用"
    
    return {
        "status": "success",
        "config": config,
        "message": message
    }


@app.post("/admin/beat-schedule/trigger")
async def trigger_beat_schedule():
    """手動觸發一次掃描"""
    from .tasks import watch_folder_scan
    
    result = watch_folder_scan.apply_async()
    
    return {
        "status": "submitted",
        "task_id": result.id,
        "message": "掃描任務已提交"
    }


@app.post("/admin/index/regenerate")
async def regenerate_index():
    """
    手動重新生成 index.md
    """
    from src.index_generator import generate_index_md
    
    success = generate_index_md()
    
    if success:
        return {"status": "success", "message": "index.md 已重新生成"}
    else:
        return {"status": "error", "message": "index.md 生成失敗"}, 500


@app.get("/files")
@app.get("/api/files")
async def list_files():
    """列出已上傳的檔案"""
    from pathlib import Path
    
    raw_dir = Path("data/raw")
    if not raw_dir.exists():
        return {"files": []}

    _enforce_upload_retention()
    
    files = []
    for f in raw_dir.rglob("*"):
        if f.is_file():
            relative_path = f.relative_to(raw_dir)
            category = relative_path.parts[0] if len(relative_path.parts) > 1 else None
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "path": str(relative_path),
                "category": category,
                "mtime": f.stat().st_mtime_ns,
            })
    
    files.sort(key=lambda item: (item["mtime"], item["path"]), reverse=True)
    return {"files": files}


@app.get("/api/category-stats")
async def get_category_stats():
    """
    取得每個分類的搜尋機率分數
    用於熱圖卡片顯示強弱狀態
    
    計算公式（根據搜尋次數）：
      score = sum(search_count) per category
    
    判定標準：
      - 強：score >= 10
      - 弱：1 <= score < 10
      - 無：score = 0
    """
    from neo4j import GraphDatabase
    from ..main import load_config
    
    # 定義分類對應（使用英文名稱）
    CATEGORY_FILES = {
        '4G/5G': ['4G_Volte_Optimization.md','5G_NR_Bearer_Establishment.md','5G_NR_NSA_SA_Comparison.md','LTE_Handover_Analysis.md','LTE_Parameter_Planning.md','LTE_PDSCH_Optimization.md','LTE_S1_U_Troubleshooting.md','NR_Beamforming_Config.md','NR_CA_Configuration.md','NR_SCell_Config.md'],
        'WiFi': ['Captive_Portal_Config.md','IOT_WiFi_Separation.md','Mesh_Network_Design.md','WiFi6_AP_Deployment.md','WiFi7_Introduction.md','WiFi_Channel_Planning.md','WiFi_Troubleshooting_Guide.md','Wireless_Security_Hardening.md'],
        'Lab': ['Consumables_Inventory.md','Equipment_Borrowing_Procedure.md','Instrument_Calibration_Record.md','Lab_Safety_Regulation.md','Network_Test_Bed_Manual.md','New_Equipment_Onboarding.md','Temperature_Humidity_Log.md'],
        'Project': ['Project_Charter_Template.md','Project_Close_Report.md','Resource_Allocation_Plan.md','Risk_Management_Register.md','Testing_UAT_Plan.md','Weekly_Status_Report.md'],
        'Automation': ['Automated_Test_Script.md','CI_CD_Pipeline_Config.md','Kubernetes_Deployment.md','Monitoring_Alert_Setup.md'],
    }
    
    # Neo4j 查詢
    try:
        config = load_config()
        neo4j_config = config.get("neo4j", {})
        driver = GraphDatabase.driver(
            neo4j_config.get("uri", "bolt://neo4j:7687"),
            auth=(
                neo4j_config.get("user", "neo4j"),
                neo4j_config.get("password") or os.getenv("NEO4J_PASSWORD", ""),
            ),
        )
        with driver.session() as session:
            result = session.run("""
                MATCH (d:Document)
                RETURN d.name as doc_name,
                       coalesce(d.search_count, 0) as search_count
            """)
            doc_stats = list(result)
        driver.close()
    except Exception as e:
        return {"error": f"Neo4j error: {str(e)}"}
    
    # 計算每個分類的分數
    results = []
    for category, filenames in CATEGORY_FILES.items():
        # 找出屬於這個分類的文件
        cat_docs = [r for r in doc_stats if r['doc_name'] in [f.replace('.md','') for f in filenames]]
        
        # 使用搜尋次數計算分數
        score = sum(r['search_count'] for r in cat_docs)
        docs = len(cat_docs)
        
        # 判定狀態（4級制）
        if score >= 20:
            status = 'strong'   # 強
        elif score >= 10:
            status = 'medium'   # 中
        elif score >= 1:
            status = 'weak'     # 弱
        else:
            status = 'none'     # 無
        
        results.append({
            "name": category,
            "status": status,
            "score": score,
            "docs": docs,
            "search_count": score,
            "files": filenames
        })
    
    # 加入空的分類（TBC-6 ~ TBC-24）
    for i in range(6, 25):
        results.append({
            "name": f"TBC-{i}",
            "status": 'none',
            "score": 0,
            "docs": 0,
            "search_count": 0,
            "files": []
        })
    
    return {"categories": results}





@app.get("/api/category-files", tags=["Documents"])
async def get_category_files(category: str = None):
    """
    取得指定分類的所有檔案列表（帶時間戳，最新在前）
    
    Query Parameters:
    - category: 分類名稱（如 4G/5G, WiFi, Lab, Project, Automation）
    
    Returns:
    - 200: 檔案列表（按 modified 時間降序）
    - 400: 缺少 category 參數
    """
    if not category:
        return {"error": "Missing category"}, 400
    
    import datetime
    data_base = _load_data_base()
    actual_category = DOCUMENT_CATEGORY_MAPPING.get(category, category)

    search_roots = [
        data_base / "processed" / actual_category,
        data_base / "uploads" / actual_category,
    ]

    files_by_stem: dict[str, dict] = {}
    for root in search_roots:
        if not root.exists():
            continue
        for file_path in root.rglob("*"):
            if not file_path.is_file() or file_path.suffix not in {".md", ".txt", ".MD"}:
                continue

            doc_name = file_path.stem
            stat_info = file_path.stat()
            modified_epoch = stat_info.st_mtime
            current = files_by_stem.get(doc_name)
            if current and current["modified_epoch"] >= modified_epoch:
                continue

            files_by_stem[doc_name] = {
                "name": doc_name,
                "full_name": file_path.name,
                "modified": datetime.datetime.fromtimestamp(modified_epoch).strftime("%Y-%m-%d %H:%M"),
                "modified_epoch": modified_epoch,
            }

    files = sorted(files_by_stem.values(), key=lambda x: x["modified_epoch"], reverse=True)
    for file_info in files:
        file_info.pop("modified_epoch", None)
    
    logger.info(f"[CategoryFiles] category={category}, count={len(files)}")
    
    return {
        "category": category,
        "files": files,
        "count": len(files)
    }


@app.get("/api/document", tags=["Documents"])
async def get_document_content(category: str = None, doc_name: str = None):
    """
    取得文件內容
    
    從 /data/processed/{category}/ 讀取對應的 Markdown 文件內容
    
    Path Parameters:
    - category: 類別名稱（如 4G_5G, WiFi, Lab, Project, Automation）
                注意：4G/5G 會被 URL 編碼為 4G_5G
    - doc_name: 文件名稱（不含副檔名，如 LTE_Parameter_Planning）
    
    Returns:
    - 200: 文件內容
    - 404: 檔案不存在
    - 500: 讀取失敗
    """
    import urllib.parse

    data_base = _load_data_base()
    category = urllib.parse.unquote(category or "")
    doc_name = os.path.basename(doc_name or "")

    content, found_path, searched_paths = _find_document_content(data_base, category, doc_name)

    if content is None:
        return {
            "error": "File not found",
            "category": category,
            "doc_name": doc_name,
            "searched_paths": searched_paths,
        }, 404
    
    # Get file modified time
    import datetime
    stat_info = os.stat(found_path)
    modified_time = datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime("%Y-%m-%d %H:%M")
    
    logger.info(f"[Document] Read {found_path}, length={len(content)}, modified={modified_time}")
    
    return {
        "category": category,
        "doc_name": doc_name,
        "full_path": found_path,
        "content": content,
        "content_length": len(content),
        "modified": modified_time
    }

@app.post("/api/increment-search-count")
async def increment_search_count(doc_name: str):
    """
    增加特定文件的搜尋次數
    在搜尋結果回傳後呼叫
    """
    from neo4j import GraphDatabase
    from ..main import load_config
    
    try:
        config = load_config()
        neo4j_config = config.get("neo4j", {})
        driver = GraphDatabase.driver(
            neo4j_config.get("uri", "bolt://neo4j:7687"),
            auth=(
                neo4j_config.get("user", "neo4j"),
                neo4j_config.get("password") or os.getenv("NEO4J_PASSWORD", ""),
            ),
        )
        with driver.session() as session:
            session.run("""
                MATCH (d:Document {name: $doc_name})
                SET d.search_count = coalesce(d.search_count, 0) + 1
            """, doc_name=doc_name)
        driver.close()
        return {"status": "success", "doc_name": doc_name}
    except Exception as e:
        return {"error": str(e)}



# ===== 啟動範例 =====

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=4)


if __name__ == "__main__":
    main()
# ============================================
# Skills Management API
# ============================================

@app.get("/skills", tags=["Skills"])
@app.get("/api/skills", tags=["Skills"])
async def get_skills():
    """取得所有 Skills 列表（系統 + Workspace）"""
    
    system_skills_dir = os.path.expanduser("~/.npm-global/lib/node_modules/openclaw/skills")
    workspace_skills_dir = os.path.join(WORKSPACE_DIR, "skills")
    
    system_skills = []
    workspace_skills = []
    
    # 讀取系統 Skills
    if os.path.exists(system_skills_dir):
        for skill_name in os.listdir(system_skills_dir):
            skill_path = os.path.join(system_skills_dir, skill_name)
            if os.path.isdir(skill_path):
                desc = ""
                sk_md = os.path.join(skill_path, "SKILL.md")
                if os.path.exists(sk_md):
                    with open(sk_md, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # 嘗試從 YAML frontmatter 讀取 description
                        import re
                        match = re.search(r'^description:\s*"([^"]+)"', content, re.MULTILINE)
                        if match:
                            desc = match.group(1)
                        else:
                            # 沒有 YAML，取第一個 Markdown 標題
                            match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                            if match:
                                desc = match.group(1)
                
                system_skills.append({
                    "name": skill_name,
                    "description": desc or "系統內建 Skill",
                    "path": skill_path,
                    "type": "system"
                })
    
    # 讀取 Workspace Skills
    if os.path.exists(workspace_skills_dir):
        for skill_name in os.listdir(workspace_skills_dir):
            skill_path = os.path.join(workspace_skills_dir, skill_name)
            if os.path.isdir(skill_path):
                desc = ""
                sk_md = os.path.join(skill_path, "SKILL.md")
                if os.path.exists(sk_md):
                    with open(sk_md, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # 嘗試從 YAML frontmatter 讀取 description
                        import re
                        match = re.search(r'^description:\s*"([^"]+)"', content, re.MULTILINE)
                        if match:
                            desc = match.group(1)
                        else:
                            # 沒有 YAML，取第一個 Markdown 標題
                            match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
                            if match:
                                desc = match.group(1)
                
                # 計算檔案數
                file_count = sum(1 for f in os.listdir(skill_path) if os.path.isfile(os.path.join(skill_path, f)))
                has_refs = os.path.exists(os.path.join(skill_path, "references"))
                
                workspace_skills.append({
                    "name": skill_name,
                    "description": desc or "自訂 Skill",
                    "path": skill_path,
                    "type": "workspace",
                    "files": file_count,
                    "hasReferences": has_refs
                })
    
    return {
        "system": system_skills,
        "workspace": workspace_skills,
        "total": len(system_skills) + len(workspace_skills)
    }


@app.get("/skills/{skill_name}", tags=["Skills"])
@app.get("/api/skills/{skill_name}", tags=["Skills"])
async def get_skill_detail(skill_name: str):
    """取得特定 Skill 的詳細資訊"""
    
    # 搜尋路徑
    search_paths = [
        os.path.expanduser("~/.npm-global/lib/node_modules/openclaw/skills"),
        os.path.join(WORKSPACE_DIR, "skills")
    ]
    
    for base_path in search_paths:
        skill_path = os.path.join(base_path, skill_name)
        if os.path.exists(skill_path) and os.path.isdir(skill_path):
            sk_md = os.path.join(skill_path, "SKILL.md")
            
            content = ""
            if os.path.exists(sk_md):
                with open(sk_md, 'r', encoding='utf-8') as f:
                    content = f.read()
            
            refs_path = os.path.join(skill_path, "references")
            references = []
            if os.path.exists(refs_path):
                references = [f for f in os.listdir(refs_path) if f.endswith('.md')]
            
            return {
                "name": skill_name,
                "path": skill_path,
                "type": "system" if "openclaw/skills" in base_path else "workspace",
                "content": content,
                "references": references
            }
    
    raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")

# ============================================
# Skill Files API (讀取/寫入 Skill 檔案)
# ============================================

@app.get("/skills/{skill_name}/files/{filename}", tags=["Skills"])
@app.get("/api/skills/{skill_name}/files/{filename}", tags=["Skills"])
async def get_skill_file(skill_name: str, filename: str):
    """讀取特定 Skill 的檔案內容"""
    
    # 搜尋路徑
    search_paths = [
        os.path.expanduser("~/.npm-global/lib/node_modules/openclaw/skills"),
        os.path.join(WORKSPACE_DIR, "skills")
    ]
    
    for base_path in search_paths:
        file_path = os.path.join(base_path, skill_name, filename)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return {
                    "name": skill_name,
                    "filename": filename,
                    "content": content,
                    "type": "workspace" if "workspace" in base_path else "system"
                }
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"讀取檔案失敗: {e}")
    
    raise HTTPException(status_code=404, detail=f"檔案 '{filename}' 不存在於 Skill '{skill_name}'")


@app.put("/skills/{skill_name}/files/{filename}", tags=["Skills"])
@app.put("/api/skills/{skill_name}/files/{filename}", tags=["Skills"])
async def update_skill_file(skill_name: str, filename: str, request: Request):
    """寫入特定 Skill 的檔案內容（僅限 Workspace Skills）"""
    
    # 只允許編輯 workspace skills
    workspace_path = os.path.join(WORKSPACE_DIR, "skills")
    skill_path = os.path.join(workspace_path, skill_name)
    file_path = os.path.join(skill_path, filename)
    
    # 檢查是否為 workspace skill
    if not os.path.exists(skill_path):
        raise HTTPException(status_code=403, detail="只能編輯 Workspace Skills")
    
    # 安全檢查：防止路徑遍历
    if ".." in skill_name or ".." in filename:
        raise HTTPException(status_code=400, detail="無效的路徑")
    
    # 讀取請求內容
    body = await request.json()
    content = body.get("content", "")
    
    # 自動備份（如果檔案已存在）
    if os.path.exists(file_path):
        backup_dir = os.path.join(skill_path, ".backups")
        os.makedirs(backup_dir, exist_ok=True)
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = os.path.join(backup_dir, f"{filename}.{timestamp}.bak")
        with open(file_path, 'r', encoding='utf-8') as f:
            old_content = f.read()
        with open(backup_file, 'w', encoding='utf-8') as f:
            f.write(old_content)
    
    # 寫入新內容
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return {"status": "ok", "message": f"檔案 '{filename}' 已更新", "backup_created": os.path.exists(backup_file) if 'backup_file' in dir() else False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"寫入檔案失敗: {e}")


@app.get("/skills/{skill_name}/files", tags=["Skills"])
@app.get("/api/skills/{skill_name}/files", tags=["Skills"])
async def list_skill_files(skill_name: str):
    """列出特定 Skill 的所有檔案"""
    
    search_paths = [
        os.path.expanduser("~/.npm-global/lib/node_modules/openclaw/skills"),
        os.path.join(WORKSPACE_DIR, "skills")
    ]
    
    for base_path in search_paths:
        skill_path = os.path.join(base_path, skill_name)
        if os.path.exists(skill_path) and os.path.isdir(skill_path):
            files = []
            for f in os.listdir(skill_path):
                if f.startswith('.'):
                    continue
                file_path = os.path.join(skill_path, f)
                if os.path.isfile(file_path):
                    from datetime import datetime
                    stat = os.stat(file_path)
                    files.append({
                        "name": f,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                    })
            
            return {
                "skill_name": skill_name,
                "files": files,
                "type": "workspace" if "workspace" in base_path else "system"
            }
    
    raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' 不存在")
