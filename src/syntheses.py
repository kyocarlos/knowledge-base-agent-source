"""
知識庫 Syntheses 層
預先生成常見問題的答案，加速未來查詢
"""

import logging
import os
from typing import Dict, List, Optional
from pathlib import Path
import yaml
import hashlib
from datetime import datetime

logger = logging.getLogger(__name__)

# Syntheses 集合的名稱
SYNTHESES_COLLECTION = "kb_syntheses"

# 觸發閾值：問題被問多少次後生成 synthesis
THRESHOLD_COUNT = 3


def get_syntheses_collection() -> str:
    """取得 Syntheses collection 名稱"""
    return SYNTHESES_COLLECTION


def get_threshold() -> int:
    """取得觸發閾值"""
    return THRESHOLD_COUNT


def check_similarity(query1: str, query2: str) -> float:
    """
    檢查兩個問題的相似度（簡單版本）
    未来可以改用向量相似度
    
    Returns:
        float: 0.0 ~ 1.0 的相似度
    """
    # 轉小寫
    q1 = query1.lower().strip()
    q2 = query2.lower().strip()
    
    # 完全相同
    if q1 == q2:
        return 1.0
    
    # 一個包含另一個
    if q1 in q2 or q2 in q1:
        return 0.8
    
    # 簡單的單字重疊計算
    words1 = set(q1.replace("?", "").split())
    words2 = set(q2.replace("?", "").split())
    
    if not words1 or not words2:
        return 0.0
    
    overlap = words1 & words2
    similarity = len(overlap) / max(len(words1), len(words2))
    
    return similarity


def get_qdrant_client():
    """取得 QDrant 客戶端"""
    from qdrant_client import QdrantClient
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    qdrant_url = os.getenv("QDRANT_URL") or config.get("qdrant", {}).get("url", "http://host.docker.internal:6333")
    return QdrantClient(url=qdrant_url)


def make_point(doc_id: str, payload: dict) -> dict:
    """建立帶有 dummy vector 的 point"""
    return {
        "id": doc_id,
        "vector": [0.0],  # QDrant 預設 vector（unnamed key）
        "payload": payload
    }


def ensure_collection():
    """確保 Syntheses collection 存在"""
    client = get_qdrant_client()
    collections = client.get_collections().collections
    collection_names = [c.name for c in collections]
    
    if SYNTHESES_COLLECTION not in collection_names:
        # 使用預設 vector（unnamed）- size=1 足夠只是為了相容
        client.create_collection(
            collection_name=SYNTHESES_COLLECTION,
            vectors_config={
                "size": 1, 
                "distance": "Cosine"
            }
        )
        logger.info(f"建立 Syntheses collection: {SYNTHESES_COLLECTION}")


def get_all_syntheses() -> List[Dict]:
    """
    取得所有已儲存的 syntheses
    """
    try:
        client = get_qdrant_client()
        ensure_collection()
        
        # 取得所有 points
        result = client.scroll(
            collection_name=SYNTHESES_COLLECTION,
            limit=100,
            with_vectors=False
        )
        
        syntheses = []
        for point in result[0]:
            payload = point.payload
            syntheses.append({
                "id": point.id,
                "question": payload.get("question", ""),
                "answer": payload.get("answer", ""),
                "sources": payload.get("sources", []),
                "query_count": payload.get("query_count", 1),
                "created_at": payload.get("created_at", ""),
                "is_ready": payload.get("is_ready", False),
            })
        
        return syntheses
        
    except Exception as e:
        logger.warning(f"無法取得 Syntheses: {e}")
        return []


def find_similar_synthesis(query: str, threshold: float = 0.8) -> Optional[Dict]:
    """
    找相似的已儲存 synthesis
    
    Args:
        query: 問題
        threshold: 相似度閾值（超過此值視為相同問題）
    
    Returns:
        Optional[Dict]: 找到的 synthesis，否則 None
    """
    all_syntheses = get_all_syntheses()
    
    best_match = None
    best_similarity = 0.0
    
    for synth in all_syntheses:
        similarity = check_similarity(query, synth.get("question", ""))
        if similarity > best_similarity and similarity >= threshold:
            best_similarity = similarity
            best_match = synth
    
    if best_match:
        logger.info(f"找到相似 synthesis (相似度: {best_similarity:.2f}): {best_match.get('question', '')[:50]}")
    
    return best_match


def track_query(question: str) -> int:
    """
    追蹤問題被問的次數
    如果是新問題，建立追蹤 record
    如果是舊問題，增加計數
    
    Returns:
        int: 當前被問次數
    """
    # 先找相似的
    synth = find_similar_synthesis(question, threshold=0.85)
    
    if synth:
        new_count = synth.get("query_count", 0) + 1
        # 更新計數
        try:
            client = get_qdrant_client()
            ensure_collection()
            
            doc_id = hashlib.md5(question.encode()).hexdigest()
            
            client.upsert(
                collection_name=SYNTHESES_COLLECTION,
                points=[make_point(doc_id, {
                    **synth,
                    "query_count": new_count,
                    "last_queried": datetime.now().isoformat(),
                })]
            )
            logger.info(f"更新 query_count: {new_count}")
            return new_count
        except Exception as e:
            logger.error(f"更新 query_count 失敗: {e}")
            return synth.get("query_count", 1)
    else:
        # 新問題，建立追蹤 record（不生成答案，只追蹤）
        try:
            client = get_qdrant_client()
            ensure_collection()
            
            doc_id = hashlib.md5(question.encode()).hexdigest()
            
            client.upsert(
                collection_name=SYNTHESES_COLLECTION,
                points=[make_point(doc_id, {
                    "question": question,
                    "answer": "",  # 尚未生成答案
                    "sources": [],
                    "query_count": 1,
                    "created_at": datetime.now().isoformat(),
                    "last_queried": datetime.now().isoformat(),
                    "is_ready": False,
                })]
            )
            logger.info(f"新問題追蹤: {question[:50]}...")
            return 1
        except Exception as e:
            logger.error(f"追蹤問題失敗: {e}")
            return 1


def should_generate_synthesis(question: str) -> bool:
    """
    檢查是否應該生成 synthesis
    
    當問題被問超過 THRESHOLD_COUNT 次時返回 True
    """
    synth = find_similar_synthesis(question, threshold=0.8)  # 使用 0.8 閾值避免誤判但也不要太高
    
    if synth:
        return synth.get("query_count", 1) >= THRESHOLD_COUNT
    
    return False


def save_synthesis(question: str, answer: str, sources: List[Dict], query_count: int = 1) -> bool:
    """
    儲存一個 synthesis
    
    Args:
        question: 問題
        answer: 生成的答案
        sources: 參考來源
        query_count: 被問次數
    
    Returns:
        bool: 是否成功
    """
    try:
        client = get_qdrant_client()
        ensure_collection()
        
        doc_id = hashlib.md5(question.encode()).hexdigest()
        
        # 寫入 point
        client.upsert(
            collection_name=SYNTHESES_COLLECTION,
            points=[make_point(doc_id, {
                "question": question,
                "answer": answer,
                "sources": sources,
                "query_count": query_count,
                "created_at": datetime.now().isoformat(),
                "is_ready": True,
            })]
        )
        
        logger.info(f"已儲存 synthesis: {question[:50]}...")
        return True
        
    except Exception as e:
        logger.error(f"儲存 Synthesis 失敗: {e}")
        return False


if __name__ == "__main__":
    # 測試
    logging.basicConfig(level=logging.INFO)
    
    print("=== Syntheses 層測試 ===")
    print(f"Collection: {get_syntheses_collection()}")
    print(f"Threshold: {get_threshold()}")
    print()
    
    # 測試相似度
    q1 = "NSA 和 SA 有什麼差別？"
    q2 = "NSA 和 SA 架構差異？"
    print(f"相似度測試: {check_similarity(q1, q2):.2f}")
    
    # 列出所有 syntheses
    all_synth = get_all_syntheses()
    print(f"\n已儲存 {len(all_synth)} 個 syntheses")
