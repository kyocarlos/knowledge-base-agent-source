"""search_task(sources_only=True) is a retrieval contract: no LLM, no report-graph answer."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _forbidden(name):
    def call(*args, **kwargs):
        raise AssertionError(f"{name} must not be called in sources_only mode")
    return call


@pytest.fixture()
def engine(monkeypatch):
    from src.web_api import tasks
    import src.main
    import src.web_api.cache as cache

    eng = MagicMock()
    eng.classify_query_intent.return_value = "lookup"
    eng._extract_document_name_hints.return_value = []
    eng._find_document_profiles_for_query.return_value = []
    eng._find_wifi_document_metadata_for_query.return_value = None
    eng._is_report_like_query.return_value = True
    eng._vector_search_raw.return_value = {"sources": [{"content": "Throughput result table", "source": "SIT-TR-SC-NR-Throughput.md", "chunk_index": 3}]}
    eng._report_graph_search_raw.side_effect = _forbidden("_report_graph_search_raw")
    eng.search.side_effect = _forbidden("search")
    eng.llm_client.chat.side_effect = _forbidden("llm_client.chat")
    eng.llm_client.generate.side_effect = _forbidden("llm_client.generate")
    kb = MagicMock(search_engine=eng)
    monkeypatch.setattr(src.main, "KnowledgeBaseSystem", lambda *a, **k: kb)
    monkeypatch.setattr(cache, "cache_get", lambda *a, **k: None)
    monkeypatch.setattr(cache, "increment_hybrid_count", lambda *a, **k: 0)
    monkeypatch.setattr(cache, "decrement_hybrid_count", lambda *a, **k: 0)
    monkeypatch.setattr(tasks, "_preloaded_vector_store", None, raising=False)
    monkeypatch.setattr(tasks, "_preloaded_llm_client", None, raising=False)
    return tasks, eng


def test_report_like_sources_only_query_never_calls_llm_or_report_graph(engine):
    tasks, eng = engine
    assert tasks._is_report_like_query("throughput 測試結果摘要")
    result = tasks.search_task.run("throughput 測試結果摘要", "vector", top_k=5, sources_only=True)
    assert result["status"] == "completed"
    assert result["sources"] and result["sources"][0]["source"] == "SIT-TR-SC-NR-Throughput.md"
    eng._report_graph_search_raw.assert_not_called()
    eng.llm_client.chat.assert_not_called()
    eng.search.assert_not_called()


def test_sources_only_keeps_requested_top_k(engine):
    tasks, eng = engine
    tasks.search_task.run("throughput 測試結果摘要", "vector", top_k=5, sources_only=True)
    requested = [call.args[1] if len(call.args) > 1 else call.kwargs.get("top_k") for call in eng._vector_search_raw.call_args_list]
    assert requested and requested[0] == 5, requested
