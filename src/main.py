"""
知識庫系統 - 主程式入口
使用範例與系統啟動
"""

import logging
import os
import yaml
from pathlib import Path
from typing import Optional

from .converter import FileConverter
from .search import SearchEngine
from .runtime_config import resolve_neo4j_uri

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """載入 config.yaml"""
    config_path = Path(__file__).parent.parent / "config" / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        neo4j_config = config.setdefault("neo4j", {})
        neo4j_config["uri"] = resolve_neo4j_uri(neo4j_config.get("uri", "bolt://neo4j:7687"))
        neo4j_config["user"] = os.getenv("NEO4J_USER", neo4j_config.get("user", "neo4j"))
        neo4j_config["password"] = os.getenv("NEO4J_PASSWORD", neo4j_config.get("password", "#*cda40da40"))
        return config
    return {}


class KnowledgeBaseSystem:
    """知識庫系統主類別"""

    def __init__(self, config_path: str = None):
        """
        初始化知識庫系統

        Args:
            config_path: 設定檔路徑（YAML 格式）
        """
        # 優先使用傳入的 config_path，否則嘗試載入 config.yaml
        if config_path is None:
            config_path = str(Path(__file__).parent.parent / "config" / "config.yaml")

        self.config = self._load_config(config_path) if Path(config_path).exists() else self._default_config()

        # 從設定檔取得 Neo4j 連線資訊
        neo4j_config = self.config.get("neo4j", {})
        ollama_config = self.config.get("ollama", {
            "base_url": "http://localhost:11434",
            "model": "gemma4:12b"
        })
        neo4j_config["uri"] = resolve_neo4j_uri(neo4j_config.get("uri", "bolt://neo4j:7687"))
        neo4j_config["user"] = os.getenv("NEO4J_USER", neo4j_config.get("user", "neo4j"))
        neo4j_config["password"] = os.getenv("NEO4J_PASSWORD", neo4j_config.get("password", "#*cda40da40"))
        search_config = self.config.get("search", {})
        self.default_basic_top_k = int(search_config.get("basic_top_k", 3))
        self.default_deep_top_k = int(search_config.get("deep_top_k", 6))

        # 初始化 Ollama 用戶端
        from .web_api.ollama_client import OllamaClient

        self.llm_client = OllamaClient(
            model=ollama_config.get("model", "gemma4:12b"),
            base_url=ollama_config.get("base_url", "http://localhost:11434")
        )

        # 初始化各模組
        self.converter = FileConverter()

        self.search_engine = SearchEngine(
            neo4j_uri=neo4j_config.get("uri", "bolt://neo4j:7687"),
            neo4j_user=neo4j_config.get("user", "neo4j"),
            neo4j_password=neo4j_config.get("password", "#*cda40da40"),
            llm_client=self.llm_client,
            llm_model=ollama_config.get("model", "gemma4:12b")
        )

        logger.info("知識庫系統初始化完成")

    def _load_config(self, config_path: str) -> dict:
        """從 YAML 檔案載入設定"""
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _default_config(self) -> dict:
        """預設設定"""
        return {
            "llm_model": "gemma4:12b",
            "neo4j_uri": "bolt://neo4j:7687",
            "neo4j_user": "neo4j",
            "neo4j_password": "#*cda40da40",
            "embedding_model": "sentence-transformers/all-MiniLM-L6-v2"
        }

    # ===== 檔案轉換 =====

    def convert_file(self, input_path: str, output_path: str = None) -> dict:
        """轉換單一檔案為 Markdown"""
        return self.converter.convert_file(input_path, output_path)

    def convert_folder(self, input_folder: str, output_folder: str) -> list:
        """批次轉換資料夾內所有檔案"""
        return self.converter.convert_batch(input_folder, output_folder)

    # ===== 搜尋 =====

    def basic_search(self, query: str, top_k: Optional[int] = None) -> dict:
        """基本搜尋（Neo4j 文件內容搜尋）"""
        return self.search_engine.basic_search(query, top_k if top_k is not None else self.default_basic_top_k)

    def deep_search(self, query: str, mode: str = "local", top_k: Optional[int] = None) -> dict:
        """深層搜尋（GraphRAG 知識圖譜檢索）"""
        return self.search_engine.deep_search(query, mode, top_k if top_k is not None else self.default_deep_top_k)

    def search(self, query: str, mode: str = "auto", top_k: Optional[int] = None, filters: Optional[dict] = None) -> dict:
        """統一搜尋介面（auto 自動選擇模式）"""
        return self.search_engine.search(query, mode, top_k=top_k, filters=filters)

    def vector_search(self, query: str, top_k: Optional[int] = None) -> dict:
        """向量搜尋（語意向量相似度）"""
        return self.search_engine.vector_search(query, top_k if top_k is not None else self.default_basic_top_k)

    def hybrid_search(self, query: str, top_k: Optional[int] = None) -> dict:
        """混合搜尋（向量 + GraphRAG）"""
        return self.search_engine.hybrid_search(query, top_k if top_k is not None else self.default_basic_top_k)

    # ===== 知識圖譜建置（簡易版）=====

    def ingest_documents(self, markdown_folder: str) -> bool:
        """
        將 Markdown 文件攼入 Neo4j 知識圖譜（簡化版）
        請使用 src/ingest.py 進行完整攝入

        Args:
            markdown_folder: Markdown 檔案資料夾

        Returns:
            bool: 是否成功
        """
        logger.warning("請使用 python -m src.ingest 進行文件攝入")
        return False


# ===== 使用範例 =====

if __name__ == "__main__":
    print("請參考 config/config.yaml.example 設定後使用")
    print("主要類別：KnowledgeBaseSystem")
