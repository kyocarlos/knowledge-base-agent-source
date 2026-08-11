"""
Celery 任務 - 搜尋任務異步執行
"""

import json
import logging
import os
import time
import hashlib
import re
import uuid
from datetime import datetime
from pathlib import Path
from celery import Celery
from celery.signals import worker_init
from kombu import Queue
from ..storage_paths import resolve_storage_category
from app.core.job_config import JOB_CONFIG, classify_job_error

logger = logging.getLogger(__name__)

# ===== 並發控制設定 =====
MAX_CONCURRENT_PROCESSING = JOB_CONFIG.max_concurrent_processing
PROCESSING_LOCK_TTL = JOB_CONFIG.processing_lock_ttl_seconds
REDIS_URL = os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL") or "redis://redis:6379/0"
REPORT_QUERY_HINTS = (
    "report",
    "報告",
    "測試",
    "throughput",
    "performance",
    "test result",
    "test results",
    "summary",
    "rtt",
    "bler",
    "latency",
    "吞吐",
    "吞吐量",
)
REPORT_RECALL_TOP_K = 60
REPORT_FOCUS_HINTS = ("throughput", "latency", "bler", "rtt")
REPORT_PERFORMANCE_SECTION_HINTS = ("performance test",)


def _is_report_like_query(query: str) -> bool:
    text = (query or "").lower()
    if any(hint in text for hint in REPORT_QUERY_HINTS):
        return True
    return bool(re.search(r"(?:scu|sce)\d+(?!\d)", text))


def _is_report_performance_data_query(query: str) -> bool:
    text = (query or "").lower()
    return any(
        hint in text
        for hint in (
            "performance test",
            "throughput",
            "latency",
            "bler",
            "rtt",
            "tcp",
            "udp",
            "數據",
            "數值",
            "case",
            "test case",
        )
    )


def _is_report_summary_query(query: str) -> bool:
    text = (query or "").lower()
    return any(hint in text for hint in ("summary", "摘要", "總結", "概覽"))


def _build_report_focus_query(query: str) -> str:
    text = (query or "").strip()
    if not text:
        return text

    lowered = text.lower()
    focus_bits: list[str] = []
    if "performance test" not in lowered:
        focus_bits.append("Performance Test")
    if not any(hint in lowered for hint in REPORT_FOCUS_HINTS):
        focus_bits.append("throughput latency bler rtt")
    if _is_report_summary_query(text) and "test result summary" not in lowered:
        focus_bits.append("Test Result Summary")

    if not focus_bits:
        return text
    return f"{text} {' '.join(focus_bits)}".strip()


def _source_text_blob(source: dict) -> str:
    return " ".join(
        str(source.get(field, "") or "")
        for field in ("source", "section_title", "content", "answer")
    ).lower()


def _has_report_performance_sources(sources: list[dict] | None) -> bool:
    if not sources:
        return False
    for source in sources:
        blob = _source_text_blob(source)
        if any(hint in blob for hint in REPORT_PERFORMANCE_SECTION_HINTS):
            if any(detail_hint in blob for detail_hint in ("test case", "tcp throughput", "latency test")):
                return True
    return False


def _prefer_report_detailed_sources(query: str, sources: list[dict] | None) -> list[dict]:
    normalized_sources = list(sources or [])
    if not _is_report_like_query(query) or not _is_report_performance_data_query(query):
        return normalized_sources

    detailed_sources = [source for source in normalized_sources if _has_report_performance_sources([source])]
    if detailed_sources:
        return detailed_sources
    return normalized_sources


def _merge_search_sources(primary: list[dict] | None, secondary: list[dict] | None) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()

    for source in list(primary or []) + list(secondary or []):
        content = str(source.get("content", "") or "")
        key = (
            str(source.get("source", "") or "").strip().lower(),
            str(source.get("chunk_index", "") or ""),
            str(source.get("section_title", "") or "").strip().lower(),
            hashlib.sha1(content.encode("utf-8", errors="ignore")).hexdigest()[:16],
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(source)

    return merged


def _should_retry_report_query(query: str, sources: list[dict] | None) -> bool:
    if not _is_report_like_query(query):
        return False
    if _is_report_performance_data_query(query) and _has_report_performance_sources(sources):
        return False
    if _is_report_summary_query(query):
        return False

    text = (query or "").lower()
    if re.search(r"(?:scu|sce)\d+(?!\d)", text):
        return True
    return any(hint in text for hint in ("performance test", "throughput", "latency", "bler", "rtt"))


def increment_search_count_sync(doc_name: str):
    """
    同步增加文件的搜尋次數
    """
    try:
        from neo4j import GraphDatabase
        from ..main import load_config
        config = load_config()
        neo4j_config = config.get("neo4j", {})
        driver = GraphDatabase.driver(
            neo4j_config.get("uri", "bolt://neo4j:7687"),
            auth=(
                neo4j_config.get("user", "neo4j"),
                neo4j_config.get("password", "change-me"),
            )
        )
        with driver.session() as session:
            session.run("""
                MATCH (d:Document {name: $doc_name})
                SET d.search_count = coalesce(d.search_count, 0) + 1
            """, doc_name=doc_name)
        driver.close()
    except Exception as e:
        logger.error(f"Failed to increment search count for {doc_name}: {e}")


def cleanup_stale_locks(max_age_seconds: int = 60):
    """
    清除過期的 processing locks
    在 worker 啟動時呼叫，確保沒有孤兒鎖
    
    Args:
        max_age_seconds: 超過此秒數的鎖視為過期
    """
    import time
    r = get_redis_client()
    pattern = "kb:processing_lock:*"
    keys = r.keys(pattern)
    cleaned = 0
    for key in keys:
        ttl = r.ttl(key)
        if ttl == -1:  # 沒有過期時間（不應該發生），或 -2 表示已過期
            r.delete(key)
            cleaned += 1
            logger.warning(f"清除無 TTL 鎖: {key}")
    if cleaned > 0:
        logger.info(f"清理了 {cleaned} 個過期鎖")


def get_redis_client():
    """取得 Redis 客戶端"""
    import redis
    return redis.from_url(REDIS_URL)


def acquire_processing_lock(file_key: str, max_retries: int = 10, retry_delay: float = 1.0) -> bool:
    """
    嘗試取得檔案處理鎖
    
    Args:
        file_key: 檔案唯一識別 key
        max_retries: 最大重試次數
        retry_delay: 重試間隔（秒）
        
    Returns:
        bool: 是否成功取得鎖
    """
    r = get_redis_client()
    lock_key = f"kb:processing_lock:{file_key}"
    
    for attempt in range(max_retries):
        # 嘗試 SET NX（只在不存在時設定）
        if r.set(lock_key, "1", nx=True, ex=PROCESSING_LOCK_TTL):
            logger.info(f"取得處理鎖: {file_key}")
            return True
        
        # 檢查目前有多少處理中的檔案
        active_locks = count_active_processing_locks()
        if active_locks < MAX_CONCURRENT_PROCESSING:
            # 有空位，稍微等待後重試
            time.sleep(retry_delay)
        else:
            # 已達上限，等待較長時間
            logger.info(f"處理槽已滿({active_locks}/{MAX_CONCURRENT_PROCESSING})，等待中...")
            time.sleep(retry_delay * 2)
    
    logger.warning(f"無法取得處理鎖: {file_key} (已等待 {(max_retries * retry_delay):.0f} 秒)")
    return False


def release_processing_lock(file_key: str):
    """釋放檔案處理鎖"""
    r = get_redis_client()
    lock_key = f"kb:processing_lock:{file_key}"
    r.delete(lock_key)
    logger.info(f"釋放處理鎖: {file_key}")


def count_active_processing_locks() -> int:
    """計算目前處理中的檔案數量"""
    r = get_redis_client()
    pattern = "kb:processing_lock:*"
    keys = r.keys(pattern)
    return len(keys)


def is_file_being_processed(file_key: str) -> bool:
    """檢查檔案是否正在處理中"""
    r = get_redis_client()
    lock_key = f"kb:processing_lock:{file_key}"
    return r.exists(lock_key) > 0


def get_processing_status() -> dict:
    """取得目前處理狀態"""
    r = get_redis_client()
    pattern = "kb:processing_lock:*"
    keys = r.keys(pattern)
    
    return {
        "active_count": len(keys),
        "max_concurrent": MAX_CONCURRENT_PROCESSING,
        "processing_files": [k.decode() if isinstance(k, bytes) else k for k in keys]
    }

# ===== Celery 設定 =====

redis_url = REDIS_URL

celery_app = Celery(
    "knowledge_base",
    broker=redis_url,
    backend=redis_url
)

celery_app.conf.update(
    task_default_queue=JOB_CONFIG.default_queue,
    task_queues=tuple(Queue(queue) for queue in (
        JOB_CONFIG.default_queue,
        JOB_CONFIG.document_queue,
        JOB_CONFIG.indexing_queue,
        "search",
        "ingest",
    )),
    # 任務路由
    task_routes={
        "tasks.search_task": {"queue": "search"},
        "tasks.watch_folder_scan": {"queue": "search"},
        "tasks.ingest_task": {"queue": "ingest"},
    },
    # 結果過期時間
    result_expires=JOB_CONFIG.result_ttl_seconds,
    # worker 並發數
    worker_concurrency=JOB_CONFIG.max_concurrent_processing,
    # 任務超時
    task_soft_time_limit=JOB_CONFIG.soft_time_limit_seconds,
    task_time_limit=JOB_CONFIG.time_limit_seconds,
    # 失敗重試
    task_acks_late=True,
    task_reject_on_worker_lost=True,
)


# ===== Worker 啟動時預載入模型 =====

# 全域變數（程序層級快取）
_preloaded_vector_store = None
_preloaded_neo4j_driver = None
_preloaded_llm_client = None


@worker_init.connect
def preload_models(**kwargs):
    """Worker 啟動時預先載入 Vector Store 和 Neo4j 連線"""
    import warnings
    warnings.filterwarnings("ignore")
    
    global _preloaded_vector_store, _preloaded_neo4j_driver, _preloaded_llm_client
    
    logger.info("=" * 50)
    logger.info("Worker 啟動中 - 預載入模型...")
    logger.info("=" * 50)
    
    try:
        # 0. 清理過期的 processing locks
        logger.info("[0/4] 清理過期鎖...")
        cleanup_stale_locks()
        
        # 1. 預載入 Vector Store (BAAI/bge-base-zh-v1.5)
        logger.info("[1/3] 載入 Vector Store (BAAI/bge-base-zh-v1.5)...")
        from ..vector_store import VectorStore
        _preloaded_vector_store = VectorStore()
        logger.info(f"      Vector Store 維度: {_preloaded_vector_store.VECTOR_DIM}")
        logger.info(f"      QDrant 連線: ✅")
        
        # 2. 預先建立 Neo4j 連線池
        logger.info("[2/4] 測試 Neo4j 連線...")
        from neo4j import GraphDatabase
        from ..main import load_config
        config = load_config()
        neo4j_config = config.get("neo4j", {})
        _preloaded_neo4j_driver = GraphDatabase.driver(
            neo4j_config.get("uri", "bolt://neo4j:7687"),
            auth=(neo4j_config.get("user", "neo4j"), neo4j_config.get("password", "change-me"))
        )
        with _preloaded_neo4j_driver.session() as session:
            session.run("RETURN 1")
        logger.info("      Neo4j 連線: ✅")
        
        # 3. 預先初始化 Ollama Client
        logger.info("[3/4] 初始化 Ollama Client...")
        from ..web_api.ollama_client import OllamaClient
        ollama_config = config.get("ollama", {})
        _preloaded_llm_client = OllamaClient(
            model=ollama_config.get("model", "qwen3-coder-next"),
            base_url=ollama_config.get("instances", ["http://localhost:11434"])[0] if ollama_config.get("instances") else ollama_config.get("base_url", "http://localhost:11434")
        )
        logger.info("      Ollama Client: ✅")
        
        logger.info("=" * 50)
        logger.info("✅ Worker 預載入完成！所有模型已就緒")
        logger.info("=" * 50)
        
    except Exception as e:
        logger.error(f"⚠️ Worker 預載入失敗: {e}")
        logger.error("系統仍會正常運作，但首次 Vector 搜尋可能較慢")


# ===== 非同步攝入任務狀態 =====

INGEST_TASK_PREFIX = "kb:ingest_task:"
INGEST_TASK_INDEX_KEY = "kb:ingest_tasks:index"
INGEST_FILE_HASH_INDEX_KEY = "kb:ingest_tasks:file_hash_index"
INGEST_DOCUMENT_LOCK_PREFIX = "kb:ingest:document-lock:"
INGEST_DOCUMENT_LOCK_TTL = int(os.getenv("KB_INGEST_DOCUMENT_LOCK_TTL", "3600"))
INGEST_TASK_SUCCESS_TTL = 24 * 60 * 60
INGEST_TASK_FAILED_TTL = 72 * 60 * 60
INGEST_UPLOAD_ROOT = Path(os.getenv("KB_INGEST_UPLOAD_ROOT", "data/uploads"))
SOURCE_METADATA_SUFFIX = ".source.json"
SUPPORTED_WATCH_EXTENSIONS = {
    ".xlsx", ".xls", ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".txt", ".md", ".html", ".csv", ".json", ".xml", ".epub", ".msg"
}

INGEST_STATUS_META = {
    "queued": (5, "等待中", "等待背景任務處理"),
    "upload_saved": (10, "檔案已接收", "檔案已儲存，等待轉換"),
    "converting": (20, "轉換 Markdown 中", "正在轉換檔案為 Markdown"),
    "converted": (30, "轉換完成", "Markdown 轉換完成"),
    "extracting": (50, "LLM 萃取中", "正在萃取文件實體與關係"),
    "writing_neo4j": (70, "寫入知識圖譜中", "正在寫入 Neo4j 知識圖譜"),
    "writing_qdrant": (85, "寫入向量資料庫中", "正在寫入 QDrant 向量資料庫"),
    "refreshing_index": (95, "更新索引中", "正在更新 index.md"),
    "completed": (100, "攝入完成", "文件已完成攝入"),
    "failed": (0, "攝入失敗", "任務執行失敗"),
}


def create_ingest_task_id() -> str:
    """建立可讀性高、低碰撞的攝入任務 ID。"""
    return f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _ingest_task_key(task_id: str) -> str:
    return f"{INGEST_TASK_PREFIX}{task_id}"


def _cleanup_file_hash_index(task_id: str, state: dict | None = None) -> None:
    """從 file hash index 移除對應任務。"""
    r = get_redis_client()
    if state is None:
        state = get_ingest_task_state(task_id)
    file_hash = (state or {}).get("file_hash")
    if file_hash:
        r.hdel(INGEST_FILE_HASH_INDEX_KEY, file_hash)


def get_ingest_task_id_by_file_hash(file_hash: str) -> str | None:
    """依檔案 hash 找到最近一筆任務 ID。"""
    if not file_hash:
        return None
    r = get_redis_client()
    raw_task_id = r.hget(INGEST_FILE_HASH_INDEX_KEY, file_hash)
    task_id = _decode_redis_value(raw_task_id)
    return task_id if task_id else None


def get_ingest_task_state_by_file_hash(file_hash: str) -> dict | None:
    """依檔案 hash 找到對應任務狀態。"""
    task_id = get_ingest_task_id_by_file_hash(file_hash)
    if not task_id:
        return None
    state = get_ingest_task_state(task_id)
    if not state:
        r = get_redis_client()
        r.hdel(INGEST_FILE_HASH_INDEX_KEY, file_hash)
        return None
    return state


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _decode_redis_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _normalise_task_state(state: dict) -> dict:
    status = state.get("status", "queued")
    progress, status_text, step = INGEST_STATUS_META.get(status, (state.get("progress", 0), status, status))
    state.setdefault("progress", progress)
    state.setdefault("status_text", status_text)
    state.setdefault("step", step)
    state.setdefault("job_status", _job_status_for_ingest(status))
    return state


def _job_status_for_ingest(status: str) -> str:
    if status in {"queued", "upload_saved", "converting", "converted", "extracting", "writing_neo4j", "writing_qdrant", "refreshing_index"}:
        return "running" if status != "queued" else "queued"
    if status in {"completed", "success", "succeeded"}:
        return "succeeded"
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    return "failed" if status in {"failed", "error"} else status


def set_ingest_task_state(task_id: str, state: dict, ttl: int | None = None) -> dict:
    """寫入完整攝入任務狀態。"""
    r = get_redis_client()
    state = _normalise_task_state({**state, "task_id": task_id, "updated_at": _now_iso()})
    key = _ingest_task_key(task_id)
    if ttl:
        r.setex(key, ttl, json.dumps(state, ensure_ascii=False))
    else:
        r.set(key, json.dumps(state, ensure_ascii=False))
    r.zadd(INGEST_TASK_INDEX_KEY, {task_id: time.time()})
    file_hash = state.get("file_hash")
    if file_hash:
        r.hset(INGEST_FILE_HASH_INDEX_KEY, file_hash, task_id)
    return state


def get_ingest_task_state(task_id: str) -> dict | None:
    """讀取單一攝入任務狀態。"""
    r = get_redis_client()
    raw = r.get(_ingest_task_key(task_id))
    if not raw:
        return None
    try:
        return _normalise_task_state(json.loads(_decode_redis_value(raw)))
    except Exception as e:
        logger.error(f"讀取攝入任務狀態失敗 {task_id}: {e}")
        return None


def acquire_document_lock(document_id: str, owner_token: str, ttl: int = INGEST_DOCUMENT_LOCK_TTL) -> bool:
    """Acquire a Redis document lock without ever stealing another worker's lock."""
    if not document_id or not owner_token:
        return False
    return bool(get_redis_client().set(f"{INGEST_DOCUMENT_LOCK_PREFIX}{document_id}", owner_token, nx=True, ex=ttl))


def release_document_lock(document_id: str, owner_token: str) -> bool:
    """Compare-and-delete: a late worker cannot release someone else's lock."""
    if not document_id or not owner_token:
        return False
    script = """
    if redis.call('GET', KEYS[1]) == ARGV[1] then
        return redis.call('DEL', KEYS[1])
    end
    return 0
    """
    return bool(get_redis_client().eval(script, 1, f"{INGEST_DOCUMENT_LOCK_PREFIX}{document_id}", owner_token))
def update_ingest_task_state(task_id: str, **updates) -> dict:
    """局部更新攝入任務狀態。"""
    current = get_ingest_task_state(task_id) or {"task_id": task_id, "created_at": _now_iso()}
    current.update(updates)
    status = current.get("status")
    if status in INGEST_STATUS_META:
        progress, status_text, step = INGEST_STATUS_META[status]
        current["progress"] = updates.get("progress", progress)
        current["status_text"] = updates.get("status_text", status_text)
        current["step"] = updates.get("step", step)
    if "job_status" not in updates and status:
        current["job_status"] = _job_status_for_ingest(status)
    ttl = None
    if status == "completed":
        ttl = INGEST_TASK_SUCCESS_TTL
        current.setdefault("finished_at", _now_iso())
        current["ingested"] = True
    elif status == "failed":
        ttl = INGEST_TASK_FAILED_TTL
        current.setdefault("finished_at", _now_iso())
        current["ingested"] = False
    return set_ingest_task_state(task_id, current, ttl=ttl)


def list_ingest_tasks(limit: int = 50) -> list[dict]:
    """依建立時間新到舊列出攝入任務。"""
    r = get_redis_client()
    task_ids = r.zrevrange(INGEST_TASK_INDEX_KEY, 0, limit - 1)
    tasks = []
    for raw_task_id in task_ids:
        task_id = _decode_redis_value(raw_task_id)
        state = get_ingest_task_state(task_id)
        if state:
            tasks.append(state)
        else:
            r.zrem(INGEST_TASK_INDEX_KEY, task_id)
    return tasks


def get_ingest_queue_position(task_id: str) -> int:
    """估算 queued 任務排隊位置（1 表示下一個）。"""
    tasks = sorted(
        [t for t in list_ingest_tasks(limit=200) if t.get("status") == "queued"],
        key=lambda item: item.get("created_at", "")
    )
    for index, task in enumerate(tasks, start=1):
        if task.get("task_id") == task_id:
            return index
    return 0


def summarise_ingest_tasks(limit: int = 50) -> dict:
    """整理前端需要的 active/queued/recent 任務列表。"""
    tasks = list_ingest_tasks(limit=limit)
    active_statuses = {"upload_saved", "converting", "converted", "extracting", "writing_neo4j", "writing_qdrant", "refreshing_index"}
    active = [t for t in tasks if t.get("status") in active_statuses]
    queued = sorted([t for t in tasks if t.get("status") == "queued"], key=lambda item: item.get("created_at", ""))
    for index, task in enumerate(queued, start=1):
        task["queue_position"] = index
    recent = [t for t in tasks if t.get("status") in {"completed", "failed"}]
    return {"active": active, "queued": queued, "recent": recent[:20]}


def clear_ingest_task_history(statuses: list[str] | None = None) -> dict:
    """
    清除攝入任務歷史紀錄。

    只刪除指定狀態的任務，預設為 completed / failed。
    不會刪除 queued 或 active 任務。
    """
    target_statuses = set(statuses or ["completed", "failed"])
    r = get_redis_client()
    task_ids = r.zrange(INGEST_TASK_INDEX_KEY, 0, -1)
    deleted_task_ids: list[str] = []

    for raw_task_id in task_ids:
        task_id = _decode_redis_value(raw_task_id)
        state = get_ingest_task_state(task_id)
        if not state:
            r.zrem(INGEST_TASK_INDEX_KEY, task_id)
            continue

        if state.get("status") not in target_statuses:
            continue

        _cleanup_file_hash_index(task_id, state)
        r.delete(_ingest_task_key(task_id))
        r.zrem(INGEST_TASK_INDEX_KEY, task_id)
        deleted_task_ids.append(task_id)

    return {
        "deleted_count": len(deleted_task_ids),
        "deleted_task_ids": deleted_task_ids,
        "statuses": sorted(target_statuses),
    }


@celery_app.task(name="tasks.ingest_file_task", bind=True, max_retries=JOB_CONFIG.max_retries)
def ingest_file_task(self, task_id: str):
    """背景處理單一上傳檔案：轉 Markdown → 攝入 Neo4j/QDrant → 更新 index.md。"""
    state = get_ingest_task_state(task_id)
    if not state:
        logger.error(f"找不到攝入任務狀態: {task_id}")
        return {"status": "failed", "error": "找不到任務狀態", "task_id": task_id}

    document_id = state.get("document_id")
    lock_owner = uuid.uuid4().hex
    lock_acquired = False
    try:
        if document_id:
            lock_acquired = acquire_document_lock(document_id, lock_owner)
            if not lock_acquired:
                error = f"document_lock_busy: {document_id}"
                update_ingest_task_state(task_id, status="failed", error=error, ingested=False)
                try:
                    from ..ingest_registry import IngestRegistry
                    IngestRegistry().update_status(task_id, "rejected")
                    IngestRegistry().record_event("document_lock_busy", task_id, document_id=document_id)
                except Exception as registry_error:
                    logger.error("記錄 document lock 衝突失敗: %s", registry_error)
                return get_ingest_task_state(task_id) or {"task_id": task_id, "status": "failed", "error": error}
            try:
                from ..ingest_registry import IngestRegistry
                IngestRegistry().record_event("document_lock_acquired", task_id, document_id=document_id)
            except Exception as registry_error:
                logger.error("記錄 document lock 取得事件失敗: %s", registry_error)
        trace_id = (getattr(self.request, "headers", None) or {}).get("trace_id")
        update_ingest_task_state(task_id, status="upload_saved", started_at=_now_iso(), celery_task_id=self.request.id, trace_id=trace_id)

        original_path = Path(state["original_path"])
        converted_path = Path(state["converted_path"])
        extraction_mode = state.get("extraction_mode") or "4g5g"
        from ..ingest import detect_extraction_mode
        filename_mode = detect_extraction_mode(original_path.stem)
        if filename_mode != "4g5g":
            extraction_mode = filename_mode
            from ..extract_entities import get_extraction_info
            mode_info = get_extraction_info(filename_mode)
            update_ingest_task_state(
                task_id,
                extraction_mode=filename_mode,
                extraction_mode_name=mode_info.get("name", filename_mode),
                storage_category=resolve_storage_category(filename_mode, original_path.name),
            )

        update_ingest_task_state(task_id, status="converting")
        canonical_report = None
        if state.get("canonical_test_report"):
            from ..test_reports.excel_contract import parse_and_validate_report, render_report_markdown
            canonical_report = parse_and_validate_report(original_path)
            converted_path.parent.mkdir(parents=True, exist_ok=True)
            converted_path.write_text(render_report_markdown(canonical_report), encoding="utf-8")
            manifest = canonical_report["manifest"]
            converted_path.with_name(f"{converted_path.stem}.source.json").write_text(
                json.dumps({
                    "run_id": manifest["run_id"],
                    "environment": manifest["environment"],
                    "project_code": manifest["project_code"],
                    "dut_model": manifest["dut_model"],
                    "verdict": manifest["overall_verdict"],
                    "started_at": manifest["started_at"],
                    "schema_version": manifest["schema_version"],
                    "storage_category": "Report",
                    "extraction_mode": "report",
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            result = {"status": "success", "image_refs": []}
        else:
            from ..converter import FileConverter
            converter = FileConverter()
            result = converter.convert_file(str(original_path), str(converted_path))
            if result.get("status") != "success":
                raise RuntimeError(result.get("error", "轉換失敗"))

        update_ingest_task_state(task_id, status="converted", converted_path=str(converted_path))
        try:
            _write_source_metadata(
                source_path=original_path,
                source_hash=state.get("file_hash", ""),
                category_folder=state.get("storage_category") or resolve_storage_category(extraction_mode, original_path.name),
                md_path=converted_path,
                extraction_mode=extraction_mode,
                image_refs=result.get("image_refs", []),
                identity=state,
            )
        except Exception as meta_error:
            logger.warning(f"寫入來源中繼資料失敗，繼續攝入: {meta_error}")
        update_ingest_task_state(task_id, status="extracting")

        from ..ingest import ingest_document
        # ingest_document 內部會完成 LLM 萃取、Neo4j 與 QDrant 寫入；第一版以階段式狀態呈現。
        update_ingest_task_state(task_id, status="writing_neo4j")
        success = ingest_document(
            str(converted_path),
            extraction_mode=extraction_mode,
            preserve_assets=True,
        )
        if not success:
            raise RuntimeError("攝入文件失敗")

        if canonical_report is not None:
            from ..ingest import load_config, _get_neo4j_connection_info
            from ..test_reports.canonical_graph import write_canonical_test_graph
            neo4j_uri, neo4j_user, neo4j_password = _get_neo4j_connection_info(load_config())
            write_canonical_test_graph(
                canonical_report,
                doc_name=converted_path.stem,
                neo4j_uri=neo4j_uri,
                neo4j_user=neo4j_user,
                neo4j_password=neo4j_password,
            )

        update_ingest_task_state(task_id, status="writing_qdrant")
        update_ingest_task_state(task_id, status="refreshing_index")
        try:
            from src.index_generator import generate_index_md
            generate_index_md()
        except Exception as index_error:
            logger.warning(f"更新 index.md 失敗（不阻斷攝入完成）: {index_error}")

        final_state = update_ingest_task_state(
            task_id,
            status="completed",
            ingested=True,
            error=None,
            content=(converted_path.read_text(encoding="utf-8")[:5000] if converted_path.exists() else "")
        )
        if state.get("document_id"):
            try:
                from ..ingest_registry import IngestRegistry
                IngestRegistry().update_status(task_id, "completed")
                IngestRegistry().record_event("ingest_completed", task_id, document_id=state["document_id"])
            except Exception as registry_error:
                logger.error("更新攝入 registry 完成狀態失敗: %s", registry_error)
        if state.get("submission_id"):
            try:
                from ..test_reports.registry import SubmissionRegistry
                SubmissionRegistry().sync_ingest_status(state["submission_id"], final_state)
            except Exception as registry_error:
                logger.error("同步 report submission 完成狀態失敗: %s", registry_error)
        logger.info(f"攝入任務完成: {task_id} ({state.get('file_name')})")
        if lock_acquired:
            release_document_lock(document_id, lock_owner)
        return final_state

    except Exception as e:
        decision = classify_job_error(e)
        trace_id = (getattr(self.request, "headers", None) or {}).get("trace_id")
        logger.error("攝入任務失敗 task_id=%s trace_id=%s retryable=%s: %s", task_id, trace_id, decision.retryable, e)
        if decision.retryable and self.request.retries < JOB_CONFIG.max_retries:
            update_ingest_task_state(task_id, status="retrying", error=decision.reason, trace_id=trace_id)
            if lock_acquired:
                release_document_lock(document_id, lock_owner)
            raise self.retry(exc=e, countdown=JOB_CONFIG.retry_countdown_seconds)
        failed_state = update_ingest_task_state(task_id, status="failed", error=str(e))
        if state.get("document_id"):
            try:
                from ..ingest_registry import IngestRegistry
                IngestRegistry().update_status(task_id, "ingest_failed")
                IngestRegistry().record_event("ingest_failed", task_id, document_id=state["document_id"], error=str(e))
            except Exception as registry_error:
                logger.error("更新攝入 registry 失敗狀態失敗: %s", registry_error)
        if state.get("submission_id"):
            try:
                from ..test_reports.registry import SubmissionRegistry
                SubmissionRegistry().sync_ingest_status(state["submission_id"], failed_state)
            except Exception as registry_error:
                logger.error("同步 report submission 失敗狀態失敗: %s", registry_error)
        if lock_acquired:
            release_document_lock(document_id, lock_owner)
        return failed_state


# ===== 任務定義 =====

_SEARCH_CITATION_CATEGORIES = ["4G/5G", "WiFi", "Lab", "Project", "Automation"]


def _search_source_category_for_doc(doc_name: str) -> str | None:
    from pathlib import Path

    raw_name = Path(str(doc_name or "")).name.lower()
    stem = Path(raw_name).stem
    if any(k in stem or k in raw_name for k in ["sit-tr-wl", "wifi", "wi-fi", "wireless", "ssid", "mesh", "router"]):
        return "WiFi"
    if any(k in stem or k in raw_name for k in ["nr", "lte", "5g", "bear", "beam", "pdsch", "volte", "scell", "ca", "handover"]):
        return "4G/5G"
    if any(k in stem or k in raw_name for k in ["wifi", "mesh", "ssid", "channel", "ap", "wpa", "router", "5ghz", "6ghz", "2.4ghz", "unii"]):
        return "WiFi"
    if any(k in stem or k in raw_name for k in ["lab", "device", "equipment", "borrow", "calibration", "inventory"]):
        return "Lab"
    if any(k in stem or k in raw_name for k in ["project", "pm", "onboarding", "milestone", "risk", "task"]):
        return "Project"
    if any(k in stem or k in raw_name for k in ["auto", "ci/cd", "pipeline", "jenkins", "github", "workflow", "deploy"]):
        return "Automation"
    return None


def _build_search_citation_distribution(sources: list[dict]) -> dict:
    category_counts = {category: 0 for category in _SEARCH_CITATION_CATEGORIES}
    source_categories: dict[str, str | None] = {}
    unmatched_count = 0

    for source in sources or []:
        src_name = str((source or {}).get("source", "")).strip()
        if not src_name:
            unmatched_count += 1
            continue

        storage_category = str((source or {}).get("storage_category") or "").strip()
        extraction_mode = str((source or {}).get("extraction_mode") or "").strip().lower()
        category = None
        if storage_category in _SEARCH_CITATION_CATEGORIES:
            category = storage_category
        elif extraction_mode == "report":
            category = "4G/5G"
        elif extraction_mode == "simple":
            category = "4G/5G"
        else:
            category = _search_source_category_for_doc(src_name)
        source_categories[src_name] = category
        if category in category_counts:
            category_counts[category] += 1
        else:
            unmatched_count += 1

    matched_count = sum(category_counts.values())
    return {
        "category_counts": category_counts,
        "source_categories": source_categories,
        "matched_count": matched_count,
        "unmatched_count": unmatched_count,
        "total_sources": len(sources or []),
    }

@celery_app.task(name="tasks.search_task", bind=True, max_retries=JOB_CONFIG.max_retries)
def search_task(self, query: str, mode: str, top_k: int | None = None, sources_only: bool = False, **kwargs):
    """
    搜尋任務本體

    Args:
        query: 搜尋查詢
        mode: basic / deep / vector / hybrid / auto
        **kwargs: 其他參數（如 user_id）

    Returns:
        dict: 包含 answer, sources, mode
    """
    hybrid_incremented = False
    
    try:
        logger.info(f"執行搜尋任務: query={query[:50]}, mode={mode}")

        # 延遲引入，避免迴圈相依
        from ..main import KnowledgeBaseSystem
        from .cache import cache_get, increment_hybrid_count, decrement_hybrid_count

        # Hybrid 模式：增加計數
        if mode == "hybrid":
            current = increment_hybrid_count()
            hybrid_incremented = True
            logger.info(f"Hybrid 人數 +1，目前: {current}")

        # 檢查任務是否被取消
        if self.request.id and cache_get(f"cancel:{self.request.id}"):
            if hybrid_incremented:
                decrement_hybrid_count()
            return {"status": "cancelled", "message": "任務已被取消"}

        filters = kwargs.get("filters") or {}

        # 對報告型查詢拉高召回，避免只拿到 TOC / 前言
        effective_top_k = top_k
        if _is_report_like_query(query):
            effective_top_k = max(effective_top_k or 0, REPORT_RECALL_TOP_K)
            logger.info(f"Report-like query detected, top_k adjusted to {effective_top_k}")

        # 使用預載入的系統或建立新的
        kb = KnowledgeBaseSystem()
        
        # 如果有預載入的資源，注入到 kb
        global _preloaded_vector_store, _preloaded_llm_client
        if _preloaded_vector_store is not None:
            kb.search_engine.vector_store = _preloaded_vector_store
            logger.info(f"已注入預載入的 vector_store")
        else:
            logger.warning("預載入的 vector_store 為 None")
        if _preloaded_llm_client is not None:
            kb.search_engine.llm_client = _preloaded_llm_client
            logger.info(f"已注入預載入的 llm_client")

        # 僅取得 sources 時，跳過 LLM 生成，讓 browser citation sidecar 快速返回
        if sources_only:
            logger.info(f"sources_only 模式啟用，跳過 LLM 生成: query={query[:50]}, mode={mode}")
            raw_sources = []
            answer = ""
            search_mode = "vector" if mode in ("auto", "vector", "hybrid", "hybrid_plus") else mode
            query_intent = kb.search_engine.classify_query_intent(query)
            if filters:
                vector_result = kb.search_engine._vector_search_raw(query, effective_top_k, filters=filters)
                raw_sources = vector_result.get("sources", []) or []
                return {
                    "answer": "", "sources": raw_sources,
                    "citation_distribution": _build_search_citation_distribution(raw_sources),
                    "mode": "vector", "status": "completed",
                }
            wifi_specific_hints = kb.search_engine._extract_document_name_hints(query)
            document_profiles = kb.search_engine._find_document_profiles_for_query(query, limit=6)
            wifi_profiles = [
                profile for profile in document_profiles
                if kb.search_engine._document_storage_category(profile) == "WiFi"
            ]
            wifi_metas = [
                kb.search_engine._build_wifi_metadata_source(profile)
                for profile in wifi_profiles
            ]
            if query_intent == "compare" and len(wifi_metas) < 2:
                wifi_fallback_metas = kb.search_engine._find_wifi_document_metadatas_for_query(query, limit=4)
                wifi_metas = kb.search_engine._merge_wifi_metadata_candidates(wifi_metas, wifi_fallback_metas)

            if query_intent == "compare":
                if len(wifi_metas) >= 2:
                    wifi_compare_result = kb.search_engine._build_wifi_throughput_compare_answer(query, wifi_metas)
                    if wifi_compare_result is not None and wifi_compare_result.get("answer"):
                        raw_sources = wifi_compare_result.get("sources", []) or []
                        answer = wifi_compare_result.get("answer", "") or ""
                        citation_distribution = _build_search_citation_distribution(raw_sources)
                        return {
                            "answer": answer,
                            "sources": raw_sources,
                            "citation_distribution": citation_distribution,
                            "mode": wifi_compare_result.get("mode", "wifi_compare"),
                            "status": "completed"
                        }
                elif wifi_specific_hints and wifi_metas:
                    matched_wifi_docs = {
                        kb.search_engine._compact_alnum(str(meta.get("doc_name") or meta.get("source_name") or ""))
                        for meta in wifi_metas
                    }
                    matched_wifi_docs.discard("")
                    missing_hints = [
                        hint for hint in wifi_specific_hints
                        if kb.search_engine._compact_alnum(hint) not in matched_wifi_docs
                    ]
                    if missing_hints:
                        answer_lines = ["## 原文", "未找到足夠的 WiFi 文件可進行比較。", "", "## 解讀"]
                        if wifi_metas:
                            answer_lines.append(
                                "- 目前只找到：" + "、".join(
                                    str(meta.get("source_name") or meta.get("doc_name") or "WiFi 文件").strip()
                                    for meta in wifi_metas[:2]
                                )
                            )
                        answer_lines.append("- 未命中的查詢文件：" + "、".join(missing_hints))
                        raw_sources = [kb.search_engine._build_wifi_metadata_source(meta) for meta in wifi_metas[:2]]
                        citation_distribution = _build_search_citation_distribution(raw_sources)
                        return {
                            "answer": "\n".join(answer_lines).strip(),
                            "sources": raw_sources,
                            "citation_distribution": citation_distribution,
                            "mode": "wifi_compare",
                            "status": "completed"
                        }

            wifi_meta = wifi_metas[0] if wifi_metas else kb.search_engine._find_wifi_document_metadata_for_query(query)
            if wifi_meta is not None:
                wifi_doc_name = str(wifi_meta.get("doc_name") or "").strip()
                if wifi_doc_name:
                    wifi_band_result = kb.search_engine._build_wifi_throughput_band_answer(query, wifi_meta)
                    if wifi_band_result is not None and wifi_band_result.get("answer"):
                        raw_sources = wifi_band_result.get("sources", []) or []
                        answer = wifi_band_result.get("answer", "") or ""
                        citation_distribution = _build_search_citation_distribution(raw_sources)
                        return {
                            "answer": answer,
                            "sources": raw_sources,
                            "citation_distribution": citation_distribution,
                            "mode": wifi_band_result.get("mode", search_mode),
                            "status": "completed"
                        }

                    wifi_result = kb.search_engine.vector_search(query, top_k=effective_top_k, filter_doc=wifi_doc_name)
                    raw_sources = wifi_result.get("sources", []) or []
                    answer = wifi_result.get("answer", "") or ""
                    if raw_sources:
                        citation_distribution = _build_search_citation_distribution(raw_sources)
                        return {
                            "answer": answer,
                            "sources": raw_sources,
                            "citation_distribution": citation_distribution,
                            "mode": wifi_result.get("mode", search_mode),
                            "status": "completed"
                        }

            if kb.search_engine._is_report_like_query(query):
                report_graph_result = kb.search_engine._report_graph_search_raw(query, effective_top_k)
                raw_sources = report_graph_result.get("sources", []) or []
                answer = report_graph_result.get("answer", "") or ""
                if raw_sources:
                    citation_distribution = _build_search_citation_distribution(raw_sources)
                    return {
                        "answer": answer,
                        "sources": raw_sources,
                        "citation_distribution": citation_distribution,
                        "mode": report_graph_result.get("mode", search_mode),
                        "status": "completed"
                    }
            if search_mode == "vector":
                vector_result = kb.search_engine._vector_search_raw(query, effective_top_k)
                raw_sources = _prefer_report_detailed_sources(query, vector_result.get("sources", []))
                answer = vector_result.get("answer", "") or ""
                if _should_retry_report_query(query, raw_sources):
                    focused_query = _build_report_focus_query(query)
                    if focused_query != query:
                        focused_result = kb.search_engine._vector_search_raw(
                            focused_query,
                            max(effective_top_k or 0, REPORT_RECALL_TOP_K),
                        )
                        focused_sources = _prefer_report_detailed_sources(query, focused_result.get("sources", []))
                        if focused_sources:
                            raw_sources = _merge_search_sources(raw_sources, focused_sources)
                            if not answer:
                                answer = focused_result.get("answer", "") or ""
            elif search_mode in ("basic", "deep"):
                deep_result = kb.search_engine._deep_search_raw(query, mode="local", top_k=effective_top_k)
                raw_sources = deep_result.get("graph_results", []) or []
                answer = deep_result.get("answer", "") or ""
            else:
                vector_result = kb.search_engine._vector_search_raw(query, effective_top_k)
                raw_sources = _prefer_report_detailed_sources(query, vector_result.get("sources", []))
                answer = vector_result.get("answer", "") or ""
                if _should_retry_report_query(query, raw_sources):
                    focused_query = _build_report_focus_query(query)
                    if focused_query != query:
                        focused_result = kb.search_engine._vector_search_raw(
                            focused_query,
                            max(effective_top_k or 0, REPORT_RECALL_TOP_K),
                        )
                        focused_sources = _prefer_report_detailed_sources(query, focused_result.get("sources", []))
                        if focused_sources:
                            raw_sources = _merge_search_sources(raw_sources, focused_sources)
                            if not answer:
                                answer = focused_result.get("answer", "") or ""

            if raw_sources:
                citation_distribution = _build_search_citation_distribution(raw_sources)
                return {
                    "answer": answer,
                    "sources": raw_sources,
                    "citation_distribution": citation_distribution,
                    "mode": search_mode,
                    "status": "completed"
                }

            return {
                "status": "completed",
                "answer": answer,
                "sources": [],
                "citation_distribution": _build_search_citation_distribution([]),
                "mode": search_mode,
            }

        # 執行搜尋
        result = kb.search(query, mode, top_k=effective_top_k, filters=filters)

        if result.get("mode") != "report_graph" and _should_retry_report_query(query, result.get("sources", [])):
            focused_query = _build_report_focus_query(query)
            if focused_query != query:
                focused_result = kb.search(focused_query, mode, top_k=max(effective_top_k or 0, REPORT_RECALL_TOP_K), filters=filters)
                if focused_result.get("status") == "success":
                    if _has_report_performance_sources(focused_result.get("sources", [])):
                        result = focused_result

        if result.get("status") == "success":
            # 增加來源文件的搜尋次數
            sources = _prefer_report_detailed_sources(query, result.get("sources", []))
            for src in sources:
                src_name = src.get("source", "")
                if src_name:
                    increment_search_count_sync(src_name.replace('.md', ''))

            citation_distribution = _build_search_citation_distribution(sources)
            
            return {
                "answer": result.get("answer"),
                "sources": result.get("sources", []),
                "citation_distribution": citation_distribution,
                "mode": result.get("mode"),
                "status": "completed"
            }
        else:
            return {
                "status": "failed",
                "error": result.get("message", "未知錯誤"),
                "mode": mode
            }

    except Exception as e:
        trace_id = (getattr(self.request, "headers", None) or {}).get("trace_id")
        logger.error("搜尋任務失敗 trace_id=%s: %s", trace_id, e)

        # 重試機制
        decision = classify_job_error(e)
        if not decision.retryable:
            return {"status": "failed", "error": str(e), "mode": mode}
        try:
            logger.warning("搜尋任務進行重試 trace_id=%s reason=%s", trace_id, decision.reason)
            self.retry(exc=e, countdown=JOB_CONFIG.retry_countdown_seconds)
        except self.MaxRetriesExceededError:
            return {
                "status": "failed",
                "error": f"任務失敗已達最大重試次數: {e}",
                "mode": mode
            }
    finally:
        # Hybrid 模式：減少計數
        if hybrid_incremented:
            from .cache import decrement_hybrid_count
            current = decrement_hybrid_count()
            logger.info(f"Hybrid 人數 -1，目前: {current}")


@celery_app.task(name="tasks.ingest_task")
def ingest_task(markdown_folder: str, chunk_size: int = 1000, overlap: int = 200):
    """文件攼入任務（長時間執行）"""
    try:
        logger.info(f"執行攼入任務: {markdown_folder}")

        from ..main import KnowledgeBaseSystem

        kb = KnowledgeBaseSystem()
        success = kb.ingest_documents(markdown_folder, chunk_size, overlap)

        return {
            "status": "success" if success else "failed",
            "message": "攼入完成" if success else "攼入失敗"
        }

    except Exception as e:
        logger.error(f"攼入任務失敗: {e}")
        return {"status": "failed", "error": str(e)}


# ===== Celery Beat 定時任務設定 =====

from pathlib import Path
import yaml
import os

# 取得 config.yaml 路徑
_config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"

def _load_beat_config():
    """從 config.yaml 載入排程設定"""
    try:
        with open(_config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        auto_ingest = config.get("auto_ingest", {})
        return {
            "enabled": auto_ingest.get("enabled", False),
            "interval_minutes": auto_ingest.get("interval_minutes", 5),
            "watch_folder": auto_ingest.get("watch_folder", "/home/da40_ai_gb10/knowledge-base/data/watch"),
            "processed_folder": auto_ingest.get("processed_folder", "/home/da40_ai_gb10/knowledge-base/data/processed")
        }
    except Exception as e:
        logger.error(f"載入排程設定失敗: {e}")
        return {
            "enabled": False,
            "interval_minutes": 5,
            "watch_folder": "/home/da40_ai_gb10/knowledge-base/data/watch",
            "processed_folder": "/home/da40_ai_gb10/knowledge-base/data/processed"
        }

def _save_beat_config(config: dict):
    """儲存排程設定到 config.yaml"""
    try:
        with open(_config_path, "r", encoding="utf-8") as f:
            yaml_config = yaml.safe_load(f)
        
        yaml_config["auto_ingest"] = {
            "enabled": config.get("enabled", False),
            "interval_minutes": config.get("interval_minutes", 5),
            "watch_folder": config.get("watch_folder", "/home/da40_ai_gb10/knowledge-base/data/watch"),
            "processed_folder": config.get("processed_folder", "/home/da40_ai_gb10/knowledge-base/data/processed")
        }
        
        with open(_config_path, "w", encoding="utf-8") as f:
            yaml.dump(yaml_config, f, allow_unicode=True, default_flow_style=False)
        
        logger.info(f"排程設定已儲存: {config}")
        return True
    except Exception as e:
        logger.error(f"儲存排程設定失敗: {e}")
        return False

def get_beat_schedule_config():
    """取得排程設定（從 config.yaml）"""
    return _load_beat_config()

def update_beat_schedule_config(enabled=None, interval_minutes=None, watch_folder=None):
    """更新排程設定（寫入 config.yaml）"""
    config = get_beat_schedule_config()
    
    if enabled is not None:
        config["enabled"] = enabled
    if interval_minutes is not None:
        config["interval_minutes"] = interval_minutes
    if watch_folder is not None:
        config["watch_folder"] = watch_folder
    
    _save_beat_config(config)
    
    # 如果啟用了排程，更新 Celery Beat
    if config["enabled"]:
        update_celery_beat(config["interval_minutes"])
    
    return config


def update_celery_beat(interval_minutes):
    """更新 Celery Beat 排程 (即時模式)"""
    celery_app.conf.beat_schedule = {
        "process-watch-folder": {
            "task": "tasks.watch_folder_scan",
            "schedule": interval_minutes * 60,  # 轉換為秒
            "options": {}
        }
    }
    logger.info(f"Celery Beat 已更新: 每 {interval_minutes} 分鐘執行")


def _ingest_markdown_file(md_path: Path, extraction_mode: str | None = None) -> None:
    """攝入單一 Markdown 檔案。"""
    from ..ingest import ingest_document

    ingest_document(
        str(md_path),
        enable_vector=True,
        extraction_mode=extraction_mode,
        preserve_assets=True,
    )


def _is_source_metadata_file(file_path: Path) -> bool:
    return file_path.name.endswith(SOURCE_METADATA_SUFFIX)


def _source_metadata_path(source_path: Path) -> Path:
    return source_path.with_name(f"{source_path.stem}{SOURCE_METADATA_SUFFIX}")


def _file_sha256(file_path: Path) -> str:
    digest = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_unlink(file_path: Path) -> bool:
    try:
        if file_path.exists():
            file_path.unlink()
            return True
    except Exception as e:
        logger.warning(f"刪除檔案失敗: {file_path} - {e}")
    return False


def _load_source_metadata(metadata_path: Path) -> dict | None:
    if not metadata_path.exists():
        return None
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"讀取來源中繼資料失敗: {metadata_path} - {e}")
        return None


def _write_source_metadata(
    source_path: Path,
    source_hash: str,
    category_folder: str,
    md_path: Path,
    extraction_mode: str | None = None,
    image_refs: list[str] | None = None,
    identity: dict | None = None,
) -> None:
    payload = {
        "source_name": source_path.name,
        "source_stem": source_path.stem,
        "source_extension": source_path.suffix.lower(),
        "source_hash": source_hash,
        "storage_category": category_folder,
        "extraction_mode": extraction_mode or "",
        "original_path": str(source_path),
        "converted_path": str(md_path),
        "image_refs": list(image_refs or []),
        "updated_at": _now_iso(),
    }
    for key in (
        "source_system", "environment_id", "project_id", "run_id", "artifact_type",
        "report_schema", "original_file_name", "source_file_hash", "ingest_file_hash",
        "document_id", "idempotency_key", "generated_at",
    ):
        if identity and identity.get(key) not in (None, ""):
            payload[key] = identity[key]
    try:
        _source_metadata_path(source_path).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        logger.warning(f"寫入來源中繼資料失敗: {source_path} - {e}")


def _build_processed_inventory(processed_folder: Path) -> dict:
    """
    建立 processed 資料匣的已處理快取。

    回傳：
    - by_hash: source_hash -> metadata
    - by_path: relative path -> metadata
    - by_category_stem: (category, stem) -> metadata
    """
    inventory = {
        "by_hash": {},
        "by_path": {},
        "by_category_stem": {},
    }

    if not processed_folder.exists():
        return inventory

    for item in processed_folder.rglob("*"):
        if not item.is_file():
            continue
        if item.name.lower() == "index.md" or "wiki" in item.parts:
            continue

        category = item.parent.name
        rel_path = str(item.relative_to(processed_folder))
        stem_key = (category, item.stem)

        if _is_source_metadata_file(item):
            meta = _load_source_metadata(item)
            if not meta:
                continue
            source_hash = meta.get("source_hash")
            if source_hash:
                inventory["by_hash"][source_hash] = {
                    "kind": "metadata",
                    "path": item,
                    "metadata": meta,
                }
            inventory["by_path"][rel_path] = {
                "kind": "metadata",
                "path": item,
                "metadata": meta,
            }
            inventory["by_category_stem"][stem_key] = {
                "kind": "metadata",
                "path": item,
                "metadata": meta,
            }
            continue

        suffix = item.suffix.lower()
        if suffix == ".md" or suffix not in SUPPORTED_WATCH_EXTENSIONS:
            continue

        try:
            source_hash = _file_sha256(item)
        except Exception as e:
            logger.warning(f"計算 processed 檔案 hash 失敗: {item} - {e}")
            continue

        meta_path = _source_metadata_path(item)
        meta = _load_source_metadata(meta_path)
        record = {
            "kind": "source",
            "path": item,
            "metadata_path": meta_path if meta_path.exists() else None,
            "source_hash": source_hash,
            "metadata": meta,
        }
        inventory["by_hash"][source_hash] = record
        inventory["by_path"][rel_path] = record
        inventory["by_category_stem"][stem_key] = record

        if meta and meta.get("source_hash"):
            inventory["by_hash"][meta["source_hash"]] = record

    return inventory


def _record_matches_hash(record: dict | None, source_hash: str) -> bool:
    if not record:
        return False
    if record.get("source_hash") == source_hash:
        return True
    meta = record.get("metadata") or {}
    return meta.get("source_hash") == source_hash


def _sync_watch_with_processed(watch_folder: Path, processed_folder: Path) -> dict:
    """
    在正式掃描前，先對齊 watch / processed。

    若 watch 檔案與 processed 任一來源檔 hash 相同，直接刪除 watch 端重複檔。
    回傳同步統計。
    """
    processed_inventory = _build_processed_inventory(processed_folder)
    removed = []
    kept = []

    for file_path in watch_folder.iterdir():
        if not file_path.is_file():
            continue
        if _is_source_metadata_file(file_path):
            continue
        if file_path.suffix.lower() not in SUPPORTED_WATCH_EXTENSIONS:
            continue

        category_folder = resolve_storage_category(None, file_path.name)
        category_processed_dir = processed_folder / category_folder
        same_name_processed = category_processed_dir / file_path.name
        same_stem_md = category_processed_dir / f"{file_path.stem}.md"

        try:
            file_hash = _file_sha256(file_path)
        except Exception as e:
            logger.warning(f"無法計算 watch 檔案 hash，保留待處理: {file_path.name} - {e}")
            kept.append(file_path.name)
            continue

        duplicate = processed_inventory["by_hash"].get(file_hash)
        if not duplicate and same_name_processed.exists():
            duplicate = processed_inventory["by_path"].get(str(same_name_processed.relative_to(processed_folder)))
        if not duplicate and same_stem_md.exists():
            duplicate = processed_inventory["by_path"].get(str(same_stem_md.relative_to(processed_folder)))

        if _record_matches_hash(duplicate, file_hash):
            if _safe_unlink(file_path):
                removed.append(file_path.name)
                logger.info(
                    "watch 與 processed 內容相同，已刪除 watch 重複檔: %s (hash=%s)",
                    file_path.name,
                    file_hash[:12],
                )
            else:
                kept.append(file_path.name)
            continue

        if duplicate:
            logger.info(
                "watch 同名檔案內容已更新，保留以重新攝入: %s (hash=%s)",
                file_path.name,
                file_hash[:12],
            )

        kept.append(file_path.name)

    return {
        "removed": removed,
        "kept": kept,
        "processed_sources": len(processed_inventory["by_hash"]),
    }


@celery_app.task(name="tasks.watch_folder_scan", bind=True, max_retries=3)
def watch_folder_scan(self):
    """
    掃描監控資料夾，自動處理新檔案
    
    並發控制機制：
    - 使用 Redis 鎖確保同一檔案不被重複處理
    - 最大同時處理檔案數: MAX_CONCURRENT_PROCESSING (預設 2)
    - 失敗重試: 最多 3 次
    """
    # 取得目前處理狀態
    status = get_processing_status()
    logger.info(f"處理狀態: {status['active_count']}/{status['max_concurrent']} 檔案處理中")
    
    try:
        config = get_beat_schedule_config()
        from ..ingest import detect_extraction_mode
        
        if not config.get("enabled"):
            logger.info("自動攝入已停用")
            return {"status": "skipped", "message": "自動攝入已停用"}
        
        watch_folder = Path(config.get("watch_folder", "/home/da40_ai_gb10/.n8n-files/watch"))
        processed_folder = Path(config.get("processed_folder", "/home/da40_ai_gb10/knowledge-base/data/processed"))
        
        processed_folder.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"掃描監控資料夾: {watch_folder}")
        
        if not watch_folder.exists():
            logger.warning(f"監控資料夾不存在: {watch_folder}")
            return {"status": "skipped", "message": "監控資料夾不存在"}

        sync_result = _sync_watch_with_processed(watch_folder, processed_folder)
        logger.info(
            "watch/processed 同步完成: 刪除 watch 重複檔 %s 個，保留 %s 個，processed 已索引 %s 個來源",
            len(sync_result["removed"]),
            len(sync_result["kept"]),
            sync_result["processed_sources"],
        )
        
        # 取得支援的副檔名
        from ..converter import FileConverter
        converter = FileConverter()
        
        # 收集需要處理的檔案
        pending_files = []
        
        for file_path in watch_folder.iterdir():
            if not file_path.is_file():
                continue
            
            if _is_source_metadata_file(file_path):
                continue

            ext = file_path.suffix.lower()
            if ext not in SUPPORTED_WATCH_EXTENSIONS:
                continue

            try:
                file_hash = _file_sha256(file_path)
            except Exception as e:
                logger.warning(f"無法計算檔案 hash，跳過: {file_path.name} - {e}")
                continue

            category_folder = resolve_storage_category(None, file_path.name)
            category_processed_dir = processed_folder / category_folder
            category_processed_dir.mkdir(parents=True, exist_ok=True)
            pending_files.append(file_path)
        
        logger.info(f"發現 {len(pending_files)} 個待處理檔案")
        
        # 依序處理每個檔案（取得鎖後處理）
        files_processed = []
        files_failed = []
        files_waiting = []
        processed_inventory = _build_processed_inventory(processed_folder)
        processed_by_hash = set(processed_inventory["by_hash"].keys())
        
        for file_path in pending_files:
            try:
                file_hash = _file_sha256(file_path)
            except Exception as e:
                logger.warning(f"無法計算檔案 hash，跳過: {file_path.name} - {e}")
                files_failed.append((file_path.name, str(e)))
                continue

            if file_hash in processed_by_hash:
                logger.info(f"已存在相同內容，刪除 watch 重複檔: {file_path.name}")
                _safe_unlink(file_path)
                continue

            # 產生檔案唯一 key
            file_key = hashlib.md5(file_hash.encode("utf-8")).hexdigest()
            
            # 嘗試取得處理鎖
            if not acquire_processing_lock(file_key, max_retries=5, retry_delay=2.0):
                files_waiting.append(file_path.name)
                logger.info(f"無法取得鎖，跳過稍後處理: {file_path.name}")
                continue
            
            try:
                logger.info(f"處理檔案: {file_path.name}")
                category_folder = resolve_storage_category(None, file_path.name)
                category_processed_dir = processed_folder / category_folder
                category_processed_dir.mkdir(parents=True, exist_ok=True)
                
                # ===== 步驟 1: 檔案格式轉換 =====
                logger.info(f"[Step 1/4] 開始轉換: {file_path.name}")
                result = converter.convert_file(str(file_path), str(category_processed_dir / f"{file_path.stem}.md"))
                
                if result.get("status") == "success":
                    logger.info(f"[Step 1/4] 轉換成功: {file_path.name} -> {file_path.stem}.md")
                    
                    # ===== 步驟 2: 萃取 Neo4j / QDrant =====
                    logger.info(f"[Step 2/4] 開始萃取 Neo4j / QDrant: {file_path.stem}.md")
                    try:
                        _ingest_markdown_file(
                            category_processed_dir / f"{file_path.stem}.md",
                            detect_extraction_mode(file_path.stem)
                        )
                        logger.info(f"[Step 2/4] 萃取完成: {file_path.stem}.md")
                    except Exception as e:
                        logger.error(f"[Step 2/4] 萃取失敗: {e}")
                        files_failed.append((file_path.name, str(e)))
                        continue
                    
                    # ===== 步驟 3: 寫入 Neo4j 和 QDrant =====
                    logger.info(f"[Step 3/4] 寫入 Neo4j 和 QDrant: {file_path.stem}")
                    # 單檔攝入已完成

                    # ===== 步驟 4: 移動檔案到 processed =====
                    logger.info(f"[Step 4/4] 移動檔案: {file_path.name} -> processed/")
                    processed_path = category_processed_dir / file_path.name
                    if processed_path.exists():
                        try:
                            existing_hash = _file_sha256(processed_path)
                        except Exception as e:
                            logger.warning(f"無法計算 processed 檔案 hash: {processed_path} - {e}")
                            existing_hash = None
                        if existing_hash == file_hash:
                            _safe_unlink(file_path)
                        else:
                            _safe_unlink(processed_path)
                            file_path.rename(processed_path)
                    else:
                        file_path.rename(processed_path)

                    _write_source_metadata(
                        source_path=processed_path,
                        source_hash=file_hash,
                        category_folder=category_folder,
                        md_path=category_processed_dir / f"{file_path.stem}.md",
                        extraction_mode=detect_extraction_mode(file_path.stem),
                        image_refs=result.get("image_refs", []),
                    )
                    processed_by_hash.add(file_hash)
                    
                    files_processed.append(file_path.name)
                    logger.info(f"已完成全部流程: {file_path.name}")
                else:
                    logger.error(f"[Step 1/4] 轉換失敗: {file_path.name} - {result.get('error', '未知錯誤')}")
                    files_failed.append((file_path.name, result.get("error", "轉換失敗")))
                    
            except Exception as e:
                logger.error(f"處理失敗 {file_path.name}: {e}")
                files_failed.append((file_path.name, str(e)))
            finally:
                # 釋放處理鎖
                release_processing_lock(file_key)
        
        result = {
            "status": "completed",
            "processed": files_processed,
            "failed": files_failed,
            "waiting": files_waiting,
            "total": len(files_processed) + len(files_failed) + len(files_waiting),
            "processing_status": get_processing_status()
        }
        
        if files_waiting:
            logger.info(f"有 {len(files_waiting)} 個檔案等待處理（稍後 Beat 會再次觸發）")
        
        return result
        
    except Exception as e:
        logger.error(f"watch_folder_scan 任務失敗: {e}")
        return {"status": "failed", "error": str(e)}


# ===== Worker 啟動命令 =====

"""
# 啟動 Celery worker（含 Beat）
celery -A src.web_api.tasks:celery_app worker --loglevel=info --concurrency=16 -Q search &
celery -A src.web_api.tasks:celery_app beat --loglevel=info

# 或使用 systemd 管理
# /etc/systemd/system/celery-worker.service
# /etc/systemd/system/celery-beat.service
"""

__all__ = ["celery_app", "search_task", "ingest_task", "ingest_file_task", "watch_folder_scan",
           "get_processing_status", "acquire_processing_lock", "release_processing_lock",
           "create_ingest_task_id", "set_ingest_task_state", "get_ingest_task_state",
           "update_ingest_task_state", "list_ingest_tasks", "summarise_ingest_tasks",
           "get_ingest_queue_position", "INGEST_UPLOAD_ROOT", "clear_ingest_task_history"]


# ===== 模組初始化：設定 Celery Beat 排程 =====
try:
    config = get_beat_schedule_config()
    if config.get("enabled"):
        update_celery_beat(config.get("interval_minutes", 5))
        logger.info(f"Celery Beat 預設排程: 每 {config.get('interval_minutes', 5)} 分鐘執行")
except Exception as e:
    logger.warning(f"Celery Beat 初始化失敗: {e}")
