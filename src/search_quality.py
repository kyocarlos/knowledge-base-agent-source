"""Deterministic search-quality scoring and optional local reranking."""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _configured_value(env_name: str, yaml_key: str, default: str) -> str:
    value = os.getenv(env_name)
    if value:
        return value
    config_path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
    if config_path.exists():
        try:
            import yaml

            with config_path.open(encoding="utf-8") as handle:
                config = yaml.safe_load(handle) or {}
            current: object = config
            for key in yaml_key.split("."):
                current = current.get(key) if isinstance(current, dict) else None
            if current not in (None, ""):
                return str(current)
        except Exception as exc:
            logger.warning("Unable to load reranker configuration: %s", type(exc).__name__)
    return default


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def rerank_enabled() -> bool:
    return _as_bool(_configured_value("KM_RERANK_ENABLED", "search.reranker.enabled", "false"), False)


def rerank_mode() -> str:
    """Return rollout mode; the legacy enabled flag maps to active mode."""
    mode = _configured_value("KM_RERANK_MODE", "search.reranker.mode", "off").strip().lower()
    if mode not in {"off", "shadow", "active"}:
        logger.warning("Invalid KM reranker mode; using off")
        return "off"
    if mode == "off" and rerank_enabled():
        return "active"
    return mode


def _tokens(text: str) -> set[str]:
    values = re.findall(r"[\w一-鿿]+", str(text or "").lower())
    return {value for value in values if len(value) >= 2}


def lexical_overlap(query: str, content: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    return len(query_tokens & _tokens(content)) / len(query_tokens)


def document_quality_score(item: dict[str, Any]) -> float:
    """Return a bounded quality score independent from query relevance."""
    checks = [
        bool(item.get("schema_version") or item.get("package_schema_version")),
        bool(item.get("source_file_hash") or item.get("content_hash")),
        item.get("publish_status", "published") == "published",
        item.get("is_current", True) is True,
        bool(item.get("source_locator") or item.get("source_path") or item.get("source_name")),
        bool(str(item.get("content") or "").strip()),
        bool(item.get("chunk_id") or item.get("document_id")),
        bool(item.get("document_version") or item.get("embedding_version") or item.get("embedding_model")),
    ]
    return round(sum(checks) / len(checks), 4)


class LocalCrossEncoderReranker:
    """Lazy local CrossEncoder with bounded candidate count and fail-safe fallback."""

    def __init__(self, model_name: str | None = None, timeout_seconds: float | None = None):
        self.model_name = model_name or _configured_value(
            "KM_RERANK_MODEL", "search.reranker.model", "BAAI/bge-reranker-v2-m3"
        )
        configured_timeout = _configured_value("KM_RERANK_TIMEOUT_SECONDS", "search.reranker.timeout_seconds", "8")
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else float(configured_timeout)
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, max_length=512)
        return self._model

    def rerank(self, query: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        if not candidates:
            return []
        started = time.monotonic()
        model = self._load()
        pairs = [(query, str(item.get("content") or "")) for item in candidates]
        scores = model.predict(pairs, show_progress_bar=False)
        elapsed = time.monotonic() - started
        if elapsed > self.timeout_seconds:
            raise TimeoutError(f"reranker exceeded configured timeout ({self.timeout_seconds:.2f}s)")

        ranked = []
        for item, score in zip(candidates, scores):
            enriched = dict(item)
            rerank_score = float(score)
            enriched["rerank_score"] = rerank_score
            enriched["document_quality_score"] = document_quality_score(item)
            enriched["score_breakdown"] = {
                "semantic": float(item.get("score", 0.0) or 0.0),
                "lexical": lexical_overlap(query, str(item.get("content") or "")),
                "reranker": rerank_score,
                "metadata": 1.0,
                "quality": enriched["document_quality_score"],
            }
            ranked.append(enriched)

        ranked.sort(
            key=lambda item: (
                float(item.get("rerank_score", 0.0)),
                float(item.get("document_quality_score", 0.0)),
                float(item.get("score", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return ranked[:top_k]


def rerank_or_fallback(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int,
    fallback,
) -> list[dict[str, Any]]:
    mode = rerank_mode()
    if mode == "off":
        return fallback(candidates, query, top_k)
    try:
        reranked = LocalCrossEncoderReranker().rerank(query, candidates, top_k)
        if mode == "shadow":
            baseline_ids = [str(item.get("chunk_id") or item.get("id") or "") for item in candidates[:top_k]]
            shadow_ids = [str(item.get("chunk_id") or item.get("id") or "") for item in reranked]
            changed = sum(left != right for left, right in zip(baseline_ids, shadow_ids))
            logger.info("KM reranker shadow complete: candidates=%d changed_positions=%d", len(candidates), changed)
            return fallback(candidates, query, top_k)
        return reranked
    except Exception as exc:
        logger.warning("KM reranker unavailable; falling back to baseline ranking: %s", type(exc).__name__)
        return fallback(candidates, query, top_k)
