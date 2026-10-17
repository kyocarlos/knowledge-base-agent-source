"""Optional cross-encoder reranking for WiFi zone search (off unless a model is configured).

KM_WIFI8_RERANK_MODEL       sentence-transformers CrossEncoder model id ("" disables reranking)
KM_WIFI8_RERANK_CANDIDATES  fused candidates re-scored per query (default 30)
KM_WIFI8_RERANK_CHARS       characters per candidate passed to the model (default 1200)
KM_WIFI8_RERANK_MAX_LENGTH  model token limit per (query, passage) pair (default 512)
KM_WIFI8_RERANK_DEVICE      torch device (default cpu)
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Callable

Scorer = Callable[[str, list[str]], list[float]]

_models: dict[tuple[str, int, str], object] = {}
_lock = threading.Lock()


@dataclass(frozen=True)
class RerankSettings:
    model: str = ""
    candidates: int = 30
    chars: int = 1200
    max_length: int = 512
    device: str = "cpu"

    @classmethod
    def from_environment(cls) -> "RerankSettings":
        return cls(model=os.getenv("KM_WIFI8_RERANK_MODEL", "").strip(),
                   candidates=int(os.getenv("KM_WIFI8_RERANK_CANDIDATES", "30")),
                   chars=int(os.getenv("KM_WIFI8_RERANK_CHARS", "1200")),
                   max_length=int(os.getenv("KM_WIFI8_RERANK_MAX_LENGTH", "512")),
                   device=os.getenv("KM_WIFI8_RERANK_DEVICE", "cpu"))


@dataclass(frozen=True)
class Reranker:
    settings: RerankSettings
    score: Scorer


def cross_encoder_scorer(settings: RerankSettings) -> Scorer:
    """Load the model once per process (workers reuse it across tasks)."""
    key = (settings.model, settings.max_length, settings.device)
    with _lock:
        model = _models.get(key)
        if model is None:
            from sentence_transformers import CrossEncoder
            model = _models[key] = CrossEncoder(settings.model, max_length=settings.max_length, device=settings.device)

    def score(query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        return [float(s) for s in model.predict([(query, p) for p in passages], batch_size=16, show_progress_bar=False)]
    return score


def from_environment() -> Reranker | None:
    settings = RerankSettings.from_environment()
    if not settings.model:
        return None
    return Reranker(settings, cross_encoder_scorer(settings))
