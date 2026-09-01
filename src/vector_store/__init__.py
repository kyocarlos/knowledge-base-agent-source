"""
Vector Store 模組 - 使用 QDrant + BAAI/bge-base-zh-v1.5
"""

import logging
import os
import re
from typing import List, Optional, Tuple
from pathlib import Path
import yaml

from ..runtime_config import resolve_qdrant_url
from ..image_refs import extract_image_refs_from_text, merge_image_refs, normalize_asset_ref

logger = logging.getLogger(__name__)


class VectorStore:
    """向量資料庫管理器"""

    COLLECTION_NAME = "knowledge_base"
    VECTOR_DIM = 768  # BAAI/bge-base-zh-v1.5

    def __init__(self, model_name: str = "BAAI/bge-base-zh-v1.5"):
        """
        初始化向量儲存

        Args:
            model_name: Sentence Transformer 模型名稱
        """
        self.model_name = model_name
        self.model = None
        self.client = None
        self.available = True
        self._init_model()
        self._init_qdrant()

    def _init_model(self):
        """初始化 embedding 模型"""
        try:
            from sentence_transformers import SentenceTransformer
            logger.info(f"載入 embedding 模型: {self.model_name}")
            # 使用 CPU 避免 CUDA fork 問題
            self.model = SentenceTransformer(self.model_name, device='cpu')
            logger.info("Embedding 模型載入完成 (CPU mode)")
        except Exception as e:
            logger.error(f"模型載入失敗: {e}")
            raise

    def _init_qdrant(self):
        """初始化 QDrant 客戶端"""
        try:
            from qdrant_client import QdrantClient
            config_path = Path(__file__).parent.parent.parent / "config" / "config.yaml"
            qdrant_url = os.getenv("QDRANT_URL")
            if not qdrant_url and config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f) or {}
                qdrant_url = config.get("qdrant", {}).get("url", "http://host.docker.internal:6333")
            qdrant_url = resolve_qdrant_url(qdrant_url or "http://host.docker.internal:6333")
            self.client = QdrantClient(url=qdrant_url, timeout=30)
            logger.info("QDrant 客戶端連接成功")
            self._ensure_collection()
        except ImportError as e:
            self.available = False
            logger.warning(f"QDrant 客戶端未安裝，略過向量資料庫功能: {e}")
        except Exception as e:
            self.available = False
            logger.warning(f"QDrant 連接失敗，略過向量資料庫功能: {e}")

    def _ensure_collection(self):
        """確保 collection 存在"""
        try:
            from qdrant_client.models import Distance, VectorParams

            collections = self.client.get_collections().collections
            collection_names = [c.name for c in collections]

            if self.COLLECTION_NAME not in collection_names:
                self.client.create_collection(
                    collection_name=self.COLLECTION_NAME,
                    vectors_config=VectorParams(
                        size=self.VECTOR_DIM,
                        distance=Distance.COSINE
                    )
                )
                logger.info(f"建立 collection: {self.COLLECTION_NAME}")
            else:
                logger.info(f"Collection 已存在: {self.COLLECTION_NAME}")

        except Exception as e:
            logger.error(f"Collection 建立失敗: {e}")
            raise

    def encode(self, texts: List[str]) -> List[List[float]]:
        """
        將文字編碼為向量

        Args:
            texts: 文字列表

        Returns:
            向量列表
        """
        if not texts:
            return []
        embeddings = self.model.encode(texts, normalize_embeddings=True)
        return embeddings.tolist()

    def add_documents(
        self,
        documents: List[dict],
        doc_name: str,
        batch_size: int = 32
    ) -> bool:
        """
        新增文件到向量庫

        Args:
            documents: 文件分塊列表，每個包含 id, content, metadata
            doc_name: 文件名稱（用於追蹤）
            batch_size: 批次大小

        Returns:
            是否成功寫入
        """
        try:
            if not self.available or self.client is None:
                logger.warning(f"QDrant 不可用，略過文件向量寫入: {doc_name}")
                return False
            from qdrant_client.models import PointStruct

            points = []
            for i, doc in enumerate(documents):
                vector = self.encode([doc["content"]])[0]
                # QDrant 接受 UUID 或整數作為 ID
                import uuid
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{doc_name}_{i}"))

                metadata = doc.get("metadata", {}) or {}
                image_refs = merge_image_refs(
                    extract_image_refs_from_text(doc.get("content", "")),
                    metadata.get("image_refs", []),
                )

                # 使用普通 dict 作為 payload
                payload = {
                    "content": doc["content"],
                    "doc_name": doc_name,
                    "chunk_index": i,
                    "metadata": metadata,
                    "source_path": metadata.get("source_path", ""),
                    "section_title": metadata.get("header", ""),
                    "source_name": metadata.get("source_name", ""),
                    "source_ext": metadata.get("source_ext", ""),
                    "source_dir": metadata.get("source_dir", ""),
                    "storage_category": metadata.get("storage_category", ""),
                    "extraction_mode": metadata.get("extraction_mode", ""),
                    "run_id": metadata.get("run_id", ""),
                    "environment": metadata.get("environment", ""),
                    "project_code": metadata.get("project_code", ""),
                    "dut_model": metadata.get("dut_model", ""),
                    "band": metadata.get("band", ""),
                    "protocol": metadata.get("protocol", ""),
                    "direction": metadata.get("direction", ""),
                    "verdict": metadata.get("verdict", ""),
                    "started_at": metadata.get("started_at", ""),
                    "schema_version": metadata.get("schema_version", ""),
                    "source_system": metadata.get("source_system", ""),
                    "environment_id": metadata.get("environment_id", ""),
                    "project_id": metadata.get("project_id", ""),
                    "artifact_type": metadata.get("artifact_type", ""),
                    "report_schema": metadata.get("report_schema", ""),
                    "original_file_name": metadata.get("original_file_name", ""),
                    "source_file_hash": metadata.get("source_file_hash", ""),
                    "ingest_file_hash": metadata.get("ingest_file_hash", ""),
                    "document_id": metadata.get("document_id", ""),
                    "idempotency_key": metadata.get("idempotency_key", ""),
                    "generated_at": metadata.get("generated_at", ""),
                    "image_refs": image_refs,
                }

                points.append(PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload
                ))

            # 若 collection 被清掉，先自動補回來再寫入
            try:
                self._ensure_collection()
            except Exception as ensure_error:
                logger.warning(f"QDrant collection 檢查失敗，將嘗試在寫入時重建: {ensure_error}")

            # 分批寫入
            for i in range(0, len(points), batch_size):
                batch = points[i:i + batch_size]
                try:
                    self.client.upsert(
                        collection_name=self.COLLECTION_NAME,
                        points=batch
                    )
                    logger.info(f"寫入向量: {len(batch)} 筆")
                except Exception as upsert_error:
                    error_text = str(upsert_error)
                    if "doesn't exist" in error_text or "Not found: Collection" in error_text:
                        logger.warning(f"collection 不存在，重建後重試: {self.COLLECTION_NAME}")
                        self._ensure_collection()
                        self.client.upsert(
                            collection_name=self.COLLECTION_NAME,
                            points=batch
                        )
                        logger.info(f"重建 collection 後寫入向量: {len(batch)} 筆")
                    else:
                        raise

            logger.info(f"文件 {doc_name} 寫入完成，共 {len(points)} 個區塊")
            return True

        except Exception as e:
            logger.error(f"寫入向量失敗: {e}")
            raise

    def search(
        self,
        query: str,
        top_k: int = 3,
        filter_doc: Optional[str] = None,
        filters: Optional[dict] = None,
    ) -> List[dict]:
        """
        搜尋相似文件

        Args:
            query: 搜尋查詢
            top_k: 回傳數量
            filter_doc: 可選，按文件名稱過濾

        Returns:
            相似文件列表
        """
        try:
            if not self.available or self.client is None:
                return []
            from qdrant_client.models import DatetimeRange, Filter, FieldCondition, MatchAny, MatchValue

            # 編碼查詢
            query_vector = self.encode([query])[0]

            conditions = []
            if filter_doc:
                conditions.append(FieldCondition(key="doc_name", match=MatchValue(value=filter_doc)))
            allowed_filters = {
                "environment", "run_id", "project_code", "dut_model", "band",
                "protocol", "direction", "verdict", "schema_version",
                "source_system", "environment_id", "project_id", "artifact_type",
                "report_schema", "document_id", "idempotency_key",
            }
            for key, value in (filters or {}).items():
                if key not in allowed_filters or value in (None, "", []):
                    continue
                values = value if isinstance(value, list) else [value]
                conditions.append(FieldCondition(key=key, match=MatchAny(any=values)))
            date_from = (filters or {}).get("date_from")
            date_to = (filters or {}).get("date_to")
            if date_from or date_to:
                conditions.append(FieldCondition(key="started_at", range=DatetimeRange(gte=date_from, lte=date_to)))

            if conditions:
                results = self.client.query_points(
                    collection_name=self.COLLECTION_NAME,
                    query=query_vector,
                    limit=top_k,
                    query_filter=Filter(must=conditions)
                )
            else:
                results = self.client.query_points(
                    collection_name=self.COLLECTION_NAME,
                    query=query_vector,
                    limit=top_k
                )

            # 整理結果
            search_results = []
            for result in results.points:
                search_results.append({
                    "content": result.payload.get("content", ""),
                    "doc_name": result.payload.get("doc_name", ""),
                    "chunk_index": result.payload.get("chunk_index", 0),
                    "section_title": result.payload.get("section_title", ""),
                    "source_path": result.payload.get("source_path", ""),
                    "source_name": result.payload.get("source_name", ""),
                    "source_ext": result.payload.get("source_ext", ""),
                    "source_dir": result.payload.get("source_dir", ""),
                    "storage_category": result.payload.get("storage_category", ""),
                    "extraction_mode": result.payload.get("extraction_mode", ""),
                    "run_id": result.payload.get("run_id", ""),
                    "environment": result.payload.get("environment", ""),
                    "project_code": result.payload.get("project_code", ""),
                    "dut_model": result.payload.get("dut_model", ""),
                    "band": result.payload.get("band", ""),
                    "protocol": result.payload.get("protocol", ""),
                    "direction": result.payload.get("direction", ""),
                    "verdict": result.payload.get("verdict", ""),
                    "started_at": result.payload.get("started_at", ""),
                    "schema_version": result.payload.get("schema_version", ""),
                    "source_system": result.payload.get("source_system", ""),
                    "environment_id": result.payload.get("environment_id", ""),
                    "project_id": result.payload.get("project_id", ""),
                    "artifact_type": result.payload.get("artifact_type", ""),
                    "report_schema": result.payload.get("report_schema", ""),
                    "original_file_name": result.payload.get("original_file_name", ""),
                    "source_file_hash": result.payload.get("source_file_hash", ""),
                    "ingest_file_hash": result.payload.get("ingest_file_hash", ""),
                    "document_id": result.payload.get("document_id", ""),
                    "idempotency_key": result.payload.get("idempotency_key", ""),
                    "generated_at": result.payload.get("generated_at", ""),
                    "score": result.score,
                    "id": str(result.id)
                })

            return search_results

        except Exception as e:
            logger.error(f"搜尋失敗: {e}")
            return []

    def search_by_document_names(
        self,
        query: str,
        document_names: List[str],
        top_k: int = 3,
    ) -> List[dict]:
        """Retrieve chunks for resolved documents without query embedding."""
        if not self.available or self.client is None or not document_names:
            return []

        from qdrant_client.models import Filter, FieldCondition, MatchAny, MatchValue

        names = [str(name).strip() for name in document_names if str(name).strip()]
        if not names:
            return []

        visible = Filter(must=[
            FieldCondition(key="publish_status", match=MatchValue(value="published")),
            FieldCondition(key="is_current", match=MatchValue(value=True)),
            FieldCondition(key="doc_name", match=MatchAny(any=names)),
        ])
        points, _ = self.client.scroll(
            collection_name=self.COLLECTION_NAME,
            scroll_filter=visible,
            limit=256,
            with_payload=True,
            with_vectors=False,
        )
        # Legacy points predate lifecycle fields. Keep them readable during
        # migration, limited to documents resolved by the graph lookup.
        if not points:
            points, _ = self.client.scroll(
                collection_name=self.COLLECTION_NAME,
                scroll_filter=Filter(must=[
                    FieldCondition(key="doc_name", match=MatchAny(any=names)),
                ]),
                limit=256,
                with_payload=True,
                with_vectors=False,
            )

        terms = [term.lower() for term in re.findall(r"[A-Za-z0-9]+", query or "") if len(term) >= 3]
        fields = (
            "content", "doc_name", "chunk_index", "section_title", "source_path", "source_name",
            "source_ext", "storage_category", "extraction_mode", "run_id", "environment", "project_code",
            "dut_model", "band", "protocol", "direction", "verdict", "started_at", "schema_version",
            "source_system", "environment_id", "project_id", "artifact_type", "report_schema",
            "original_file_name", "source_file_hash", "ingest_file_hash", "document_id",
            "package_schema_version", "package_id", "document_version", "content_hash", "publish_status",
            "is_current", "idempotency_key", "generated_at",
        )
        results = []
        for point in points:
            payload = point.payload or {}
            blob = " ".join(str(payload.get(key, "") or "") for key in ("doc_name", "section_title", "content")).lower()
            item = {key: payload.get(key, "") for key in fields}
            item["score"] = float(sum(blob.count(term) for term in terms))
            item["id"] = str(point.id)
            results.append(item)
        results.sort(key=lambda item: (item["score"], -int(item.get("chunk_index", 0) or 0)), reverse=True)
        return results[: max(1, int(top_k))]

    def delete_by_doc(self, doc_name: str) -> bool:
        """
        刪除指定文件的所有區塊

        Args:
            doc_name: 文件名稱

        Returns:
            是否成功
        """
        try:
            if not self.available or self.client is None:
                return False
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            self.client.delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=Filter(
                    must=[FieldCondition(
                        key="doc_name",
                        match=MatchValue(value=doc_name)
                    )]
                )
            )
            logger.info(f"刪除文件: {doc_name}")
            return True

        except Exception as e:
            logger.error(f"刢除失敗: {e}")
            return False

    def clear_collection(self) -> bool:
        """
        清空整個 collection。

        這會刪除所有向量點並重建 collection，適合在整批重攝入前使用。
        """
        try:
            if not self.available or self.client is None:
                return False
            try:
                self.client.delete_collection(collection_name=self.COLLECTION_NAME)
                logger.info(f"已刪除 collection: {self.COLLECTION_NAME}")
            except Exception as delete_error:
                error_text = str(delete_error)
                if "doesn't exist" not in error_text and "Not found: Collection" not in error_text:
                    raise
                logger.info(f"collection 不存在，略過刪除: {self.COLLECTION_NAME}")

            self._ensure_collection()
            return True
        except Exception as e:
            logger.error(f"清空 collection 失敗: {e}")
            return False

    def get_stats(self) -> dict:
        """取得統計資訊"""
        try:
            if not self.available or self.client is None:
                return {"status": "unavailable"}
            try:
                info = self.client.get_collection(self.COLLECTION_NAME)
            except Exception as e:
                if "doesn't exist" in str(e) or "Not found: Collection" in str(e):
                    return {
                        "vectors_count": 0,
                        "points_count": 0,
                        "status": "missing",
                        "optimizer_status": None
                    }
                raise
            return {
                "vectors_count": info.indexed_vectors_count or 0,
                "points_count": info.points_count or 0,
                "status": info.status,
                "optimizer_status": info.optimizer_status if hasattr(info, 'optimizer_status') else None
            }
        except Exception as e:
            logger.error(f"取得統計失敗: {e}")
            return {}

    def _extract_image_refs(self, content: str) -> List[str]:
        return extract_image_refs_from_text(content)

    @staticmethod
    def _normalize_asset_ref(ref: str) -> str:
        return normalize_asset_ref(ref)

    def list_documents(self, limit: int = 1000) -> List[dict]:
        """列出 collection 內的文件摘要。"""
        try:
            if not self.available or self.client is None:
                return []
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            docs: dict[str, dict] = {}
            next_offset = None
            while True:
                points, next_offset = self.client.scroll(
                    collection_name=self.COLLECTION_NAME,
                    limit=limit,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    doc_name = str(payload.get("doc_name", "")).strip()
                    if not doc_name:
                        continue
                    doc = docs.setdefault(doc_name, {
                        "doc_name": doc_name,
                        "chunk_count": 0,
                        "source_path": payload.get("source_path", ""),
                        "source_ext": payload.get("source_ext", ""),
                        "section_titles": [],
                    })
                    doc["chunk_count"] += 1
                    source_path = payload.get("source_path", "")
                    if source_path and not doc.get("source_path"):
                        doc["source_path"] = source_path
                    section_title = payload.get("section_title", "")
                    if section_title and section_title not in doc["section_titles"]:
                        doc["section_titles"].append(section_title)
                if not next_offset:
                    break
            return sorted(docs.values(), key=lambda item: item["doc_name"])
        except Exception as e:
            logger.error(f"列出文件失敗: {e}")
            return []

    def list_chunks(self, doc_name: str) -> List[dict]:
        """列出指定文件的所有 chunk。"""
        try:
            if not self.available or self.client is None:
                return []
            from qdrant_client.models import Filter, FieldCondition, MatchValue

            chunks: List[dict] = []
            next_offset = None
            while True:
                points, next_offset = self.client.scroll(
                    collection_name=self.COLLECTION_NAME,
                    scroll_filter=Filter(
                        must=[FieldCondition(
                            key="doc_name",
                            match=MatchValue(value=doc_name)
                        )]
                    ),
                    limit=256,
                    offset=next_offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    chunks.append({
                        "id": str(point.id),
                        "doc_name": payload.get("doc_name", ""),
                        "chunk_index": payload.get("chunk_index", 0),
                        "content": payload.get("content", ""),
                        "source_path": payload.get("source_path", ""),
                        "section_title": payload.get("section_title", ""),
                        "source_name": payload.get("source_name", ""),
                        "source_ext": payload.get("source_ext", ""),
                        "source_dir": payload.get("source_dir", ""),
                        "image_refs": payload.get("image_refs", []) or [],
                        "metadata": payload.get("metadata", {}) or {},
                    })
                if not next_offset:
                    break
            return sorted(chunks, key=lambda item: item.get("chunk_index", 0))
        except Exception as e:
            logger.error(f"列出 chunk 失敗: {e}")
            return []


# 全域實例
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """取得全域 VectorStore 實例"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store
