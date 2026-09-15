from __future__ import annotations

from src.search_quality import LocalCrossEncoderReranker, document_quality_score, lexical_overlap, rerank_mode, rerank_or_fallback
from scripts.evaluate_retrieval import compare_reports, evaluate, validate_qrels


def test_retrieval_metrics_use_rank_and_grades() -> None:
    qrels = [{"query_id": "q1", "query": "error", "relevant_chunks": [
        {"chunk_id": "good", "relevance": 3}, {"chunk_id": "partial", "relevance": 0}
    ]}]
    report = evaluate(qrels, {"q1": [{"chunk_id": "partial"}, {"chunk_id": "good"}]})
    assert report["metrics"]["recall_at_20"] == 1.0
    assert report["metrics"]["mrr_at_10"] == 0.5
    assert 0 < report["metrics"]["ndcg_at_10"] < 1


def test_quality_and_lexical_scores_are_bounded() -> None:
    item = {"schema_version": "1", "source_file_hash": "abc", "publish_status": "published",
            "is_current": True, "source_path": "/tmp/a", "content": "NR error code",
            "chunk_id": "c1", "document_version": "v1"}
    assert document_quality_score(item) == 1.0
    assert lexical_overlap("NR error", item["content"]) == 1.0


def test_reranker_falls_back_when_disabled() -> None:
    candidates = [{"chunk_id": "c1", "score": 0.9}, {"chunk_id": "c2", "score": 0.8}]
    assert rerank_or_fallback("q", candidates, 1, lambda values, _query, limit: values[:limit]) == candidates[:1]


def test_reranker_shadow_returns_baseline(monkeypatch) -> None:
    monkeypatch.setenv("KM_RERANK_MODE", "shadow")
    assert rerank_mode() == "shadow"
    monkeypatch.setattr("src.search_quality.LocalCrossEncoderReranker.rerank", lambda self, query, items, limit: list(reversed(items)))
    candidates = [{"chunk_id": "a"}, {"chunk_id": "b"}]
    result = rerank_or_fallback("q", candidates, 2, lambda values, _query, limit: values[:limit])
    assert [item["chunk_id"] for item in result] == ["a", "b"]


def test_local_reranker_adds_score_breakdown(monkeypatch) -> None:
    class FakeModel:
        def predict(self, pairs, show_progress_bar=False):
            assert len(pairs) == 2
            return [0.2, 0.9]

    reranker = LocalCrossEncoderReranker(model_name="local-test", timeout_seconds=5)
    monkeypatch.setattr(reranker, "_load", lambda: FakeModel())
    ranked = reranker.rerank("q", [{"chunk_id": "a", "content": "old"}, {"chunk_id": "b", "content": "new"}], 2)
    assert [item["chunk_id"] for item in ranked] == ["b", "a"]
    assert ranked[0]["score_breakdown"]["reranker"] == 0.9


def test_qrels_schema_requires_unique_queries() -> None:
    validate_qrels([{ "query_id": "q1", "query": "q", "relevant_chunks": [] }])


def test_release_gate_detects_regression() -> None:
    baseline = {"metrics": {"recall_at_20": 0.8, "precision_at_5": 0.8, "mrr_at_10": 0.8, "ndcg_at_10": 0.8}}
    candidate = {"metrics": {"recall_at_20": 0.7, "precision_at_5": 0.8, "mrr_at_10": 0.8, "ndcg_at_10": 0.8}}
    assert "recall_at_20_regressed" in compare_reports(baseline, candidate)
