"""Deterministic search-quality scoring and optional local reranking."""

from __future__ import annotations

import logging
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
SCORE_VERSION = "km-score-v1"


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


def reranker_model_identity() -> str:
    configured = _configured_value("KM_RERANK_MODEL_ID", "search.reranker.model_id", "")
    if configured:
        return configured
    model = _configured_value("KM_RERANK_MODEL_PATH", "search.reranker.model_path", "")
    if not model:
        model = _configured_value("KM_RERANK_MODEL", "search.reranker.model", "Qwen/Qwen3-Reranker-0.6B")
    return Path(model).name or model


def embedding_model_identity() -> str:
    return _configured_value("KM_EMBEDDING_MODEL_ID", "embedding_model", "unknown")


def rerank_candidate_limit() -> int:
    raw = _configured_value("KM_RERANK_CANDIDATE_LIMIT", "search.reranker.candidate_limit", "50")
    try:
        return max(1, min(200, int(raw)))
    except ValueError:
        return 50


def rerank_torch_threads() -> int:
    raw = _configured_value("KM_RERANK_TORCH_THREADS", "search.reranker.torch_threads", "4")
    try:
        return max(1, min(16, int(raw)))
    except ValueError:
        return 4


def _aggregate_document_results(results: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
    """Limit one document from occupying the whole result page."""
    selected: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    max_per_document = 2
    for item in results:
        document_key = str(item.get("document_id") or item.get("doc_name") or item.get("source_name") or item.get("chunk_id") or item.get("id") or "unknown")
        if counts.get(document_key, 0) >= max_per_document:
            continue
        selected.append(item)
        counts[document_key] = counts.get(document_key, 0) + 1
        if len(selected) >= top_k:
            break
    return selected


def _tokens(text: str) -> set[str]:
    values = re.findall(r"[\w一-鿿]+", str(text or "").lower())
    return {value for value in values if len(value) >= 2}


def lexical_overlap(query: str, content: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    return len(query_tokens & _tokens(content)) / len(query_tokens)


def _display_score(value: object) -> int | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0.0 or numeric > 1.0:
        numeric = 1.0 / (1.0 + pow(2.718281828, -numeric))
    return max(0, min(100, round(numeric * 100)))


def _annotate_result(item: dict[str, Any], status: str) -> dict[str, Any]:
    enriched = dict(item)
    rerank_score = enriched.get("rerank_score")
    base_score = rerank_score if rerank_score is not None else enriched.get("score")
    enriched.setdefault("document_quality_score", document_quality_score(enriched))
    enriched.setdefault("rerank_score", None)
    enriched.setdefault("score_breakdown", {
        "semantic": float(enriched.get("score", 0.0) or 0.0),
        "lexical": 0.0,
        "reranker": None,
        "metadata": 1.0,
        "quality": enriched["document_quality_score"],
    })
    enriched["display_relevance_score"] = _display_score(base_score)
    display_score = enriched.get("display_relevance_score")
    enriched["relevance_grade"] = "高" if display_score is not None and display_score >= 80 else "中" if display_score is not None and display_score >= 60 else "低" if display_score is not None else "未評分"
    enriched["rerank_status"] = status
    enriched["score_version"] = SCORE_VERSION
    enriched["model_identity"] = reranker_model_identity() if status in {"active", "shadow", "fallback"} else None
    enriched["embedding_identity"] = embedding_model_identity()
    return enriched


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
            "KM_RERANK_MODEL_PATH", "search.reranker.model_path", ""
        )
        if not self.model_name:
            self.model_name = _configured_value(
                "KM_RERANK_MODEL", "search.reranker.model", "Qwen/Qwen3-Reranker-0.6B"
            )
        configured_timeout = _configured_value("KM_RERANK_TIMEOUT_SECONDS", "search.reranker.timeout_seconds", "8")
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else float(configured_timeout)
        self.torch_threads = rerank_torch_threads()
        self._model = None

    def _load(self):
        if self._model is None:
            if Path(self.model_name).is_absolute() and not Path(self.model_name).exists():
                raise FileNotFoundError("configured local reranker model path is unavailable")
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.model_name, max_length=512)
        return self._model

    def rerank(self, query: str, candidates: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        if not candidates:
            return []
        started = time.monotonic()
        model = self._load()
        pairs = [(query, str(item.get("content") or "")) for item in candidates]
        torch_module = None
        previous_torch_threads = None
        try:
            import torch

            torch_module = torch
            previous_torch_threads = torch.get_num_threads()
            torch.set_num_threads(self.torch_threads)
            try:
                scores = model.predict(
                    pairs,
                    activation_fn=torch.nn.Sigmoid(),
                    max_length=512,
                    show_progress_bar=False,
                )
            except TypeError:
                # Keep compatibility with test doubles and older CrossEncoder APIs.
                scores = model.predict(pairs, show_progress_bar=False)
        except ImportError:
            scores = model.predict(pairs, show_progress_bar=False)
        finally:
            if torch_module is not None and previous_torch_threads is not None:
                torch_module.set_num_threads(previous_torch_threads)
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
        return [_annotate_result(item, "active") for item in ranked[:top_k]]


def rerank_or_fallback(
    query: str,
    candidates: list[dict[str, Any]],
    top_k: int,
    fallback,
) -> list[dict[str, Any]]:
    mode = rerank_mode()
    query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()[:16]
    started = time.monotonic()
    if mode == "off":
        return [_annotate_result(item, "disabled") for item in fallback(candidates, query, top_k)]
    try:
        reranked = LocalCrossEncoderReranker().rerank(query, candidates, top_k)
        if mode == "shadow":
            baseline_ids = [str(item.get("chunk_id") or item.get("id") or "") for item in candidates[:top_k]]
            shadow_ids = [str(item.get("chunk_id") or item.get("id") or "") for item in reranked]
            changed = sum(left != right for left, right in zip(baseline_ids, shadow_ids))
            logger.info(
                "KM reranker shadow complete: query_hash=%s candidates=%d changed_positions=%d elapsed_ms=%d model=%s",
                query_hash, len(candidates), changed, round((time.monotonic() - started) * 1000), reranker_model_identity()
            )
            return [_annotate_result(item, "shadow") for item in fallback(candidates, query, top_k)]
        logger.info(
            "KM reranker active complete: query_hash=%s candidates=%d returned=%d elapsed_ms=%d model=%s",
            query_hash, len(candidates), len(reranked), round((time.monotonic() - started) * 1000), reranker_model_identity()
        )
        return _aggregate_document_results(reranked, top_k)
    except Exception as exc:
        logger.warning(
            "KM reranker unavailable; falling back: query_hash=%s candidates=%d elapsed_ms=%d reason=%s",
            query_hash, len(candidates), round((time.monotonic() - started) * 1000), type(exc).__name__
        )
        return [_annotate_result(item, "fallback") for item in fallback(candidates, query, top_k)]
