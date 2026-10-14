"""
Redis 快取模組 - 加速熱門查詢
"""

import json
import logging
import os
from typing import Optional, Any

import redis

logger = logging.getLogger(__name__)

# ===== Redis 連線 =====

REDIS_URL = (
    os.getenv("REDIS_URL")
    or os.getenv("CELERY_BROKER_URL")
    or "redis://redis:6379/0"
)

_redis_client = None


def get_redis_client() -> redis.Redis:
    """取得 Redis 客戶端（單例）"""
    global _redis_client

    if _redis_client is None:
        _redis_client = redis.from_url(REDIS_URL, decode_responses=True)

    return _redis_client


# ===== 快取函數 =====

def cache_get(key: str) -> Optional[Any]:
    """
    從 Redis 取得快取

    Args:
        key: 快取 key

    Returns:
        解析後的物件，或 None（找不到 / 過期）
    """
    try:
        client = get_redis_client()
        value = client.get(key)

        if value:
            logger.debug(f"快取命中: {key}")
            return json.loads(value)

        logger.debug(f"快取未命中: {key}")
        return None

    except redis.ConnectionError:
        logger.warning("Redis 連線失敗，快取功能停用")
        return None
    except Exception as e:
        logger.error(f"快取讀取錯誤: {e}")
        return None


def cache_set(key: str, value: Any, ttl: int = 3600) -> bool:
    """
    寫入 Redis 快取

    Args:
        key: 快取 key
        value: 要快取的物件（會 JSON 序列化）
        ttl: 過期秒數（預設 1 小時）

    Returns:
        bool: 是否成功
    """
    try:
        client = get_redis_client()
        serialized = json.dumps(value, ensure_ascii=False)
        if ttl is None:
            client.set(key, serialized)  # 無過期時間
        else:
            client.setex(key, ttl, serialized)
        logger.debug(f"快取寫入: {key}, ttl={ttl}s")
        return True

    except redis.ConnectionError:
        logger.warning("Redis 連線失敗，快取寫入失敗")
        return False
    except Exception as e:
        logger.error(f"快取寫入錯誤: {e}")
        return False


def cache_delete(key: str) -> bool:
    """刪除快取"""
    try:
        client = get_redis_client()
        client.delete(key)
        return True
    except Exception as e:
        logger.error(f"快取刪除錯誤: {e}")
        return False


def cache_clear_pattern(pattern: str) -> int:
    """
    刪除所有符合 pattern 的 key

    Args:
        pattern: 如 "search:*"

    Returns:
        刪除的 key 數量
    """
    try:
        client = get_redis_client()
        keys = client.keys(pattern)
        if keys:
            return client.delete(*keys)
        return 0
    except Exception as e:
        logger.error(f"快取清除錯誤: {e}")
        return 0


# ===== 常用 Key 命名 =====

def make_search_cache_key(query: str, mode: str) -> str:
    return f"search:{query[:100]}:{mode}"


def make_result_cache_key(task_id: str) -> str:
    return f"result:{task_id}"


def make_cancel_key(task_id: str) -> str:
    return f"cancel:{task_id}"


# ===== Hybrid 模式人數追蹤 =====

HYBRID_COUNT_KEY = "hybrid:active:count"
HYBRID_TTL = 300  # 5分鐘超時自動清除

def get_hybrid_count() -> int:
    """取得目前 Hybrid 模式活躍人數"""
    try:
        client = get_redis_client()
        count = client.get(HYBRID_COUNT_KEY)
        return int(count) if count else 0
    except Exception as e:
        logger.error(f"Hybrid 人數取得錯誤: {e}")
        return 0


def increment_hybrid_count() -> int:
    """增加 Hybrid 模式人數並回傳新總數"""
    try:
        client = get_redis_client()
        count = client.incr(HYBRID_COUNT_KEY)
        # 設定/更新 TTL
        client.expire(HYBRID_COUNT_KEY, HYBRID_TTL)
        logger.info(f"Hybrid 人數 +1 = {count}")
        return count
    except Exception as e:
        logger.error(f"Hybrid 人數增加錯誤: {e}")
        return 0


def decrement_hybrid_count() -> int:
    """減少 Hybrid 模式人數並回傳新總數"""
    try:
        client = get_redis_client()
        count = client.decr(HYBRID_COUNT_KEY)
        if count < 0:
            client.set(HYBRID_COUNT_KEY, 0)
            count = 0
        logger.info(f"Hybrid 人數 -1 = {count}")
        return max(0, count)
    except Exception as e:
        logger.error(f"Hybrid 人數減少錯誤: {e}")
        return 0


# ===== 熱門查詢統計 =====

def increment_query_count(query: str) -> int:
    """熱門查詢計數（用於分析哪些問題最常被問）"""
    try:
        client = get_redis_client()
        key = f"query_count:{query[:50]}"
        return client.incr(key)
    except Exception:
        return 0


def get_top_queries(limit: int = 10) -> list:
    """取得最熱門的查詢"""
    try:
        client = get_redis_client()
        keys = client.keys("query_count:*")

        queries = []
        for key in keys:
            count = int(client.get(key) or 0)
            query = key.replace("query_count:", "")
            queries.append({"query": query, "count": count})

        queries.sort(key=lambda x: x["count"], reverse=True)
        return queries[:limit]

    except Exception as e:
        logger.error(f"熱門查詢取得錯誤: {e}")
        return []
