"""
Knowledge Base System - 知識庫系統主程式
GraphRAG + RAG 雙模式搜尋架構
"""

from .converter import FileConverter
from .graphrag import GraphRAGPipeline


def __getattr__(name):
    """延遲載入重量模組，避免 package import 時連帶載入搜尋引擎。"""
    if name == "SearchEngine":
        from .search import SearchEngine

        return SearchEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["FileConverter", "GraphRAGPipeline", "SearchEngine"]
