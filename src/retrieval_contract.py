"""Canonical retrieval mode boundaries used by the application search paths."""

from __future__ import annotations

from typing import Final


RETRIEVAL_MODE_MAP: Final[dict[str, str]] = {
    "basic": "vector",
    "rag": "vector",
    "vector": "vector",
    "deep": "deep",
    "graphrag": "deep",
    "graph_rag": "deep",
    "hybrid": "hybrid",
    "hybrid_plus": "hybrid",
    "auto": "auto",
}


def resolve_retrieval_mode(mode: str | None) -> str:
    """Return the canonical mode while preserving a fail-closed boundary."""
    normalized = (mode or "auto").strip().lower()
    try:
        return RETRIEVAL_MODE_MAP[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported retrieval mode: {mode}") from exc


def retrieval_backend(mode: str) -> str:
    """Describe the data source required by a canonical retrieval mode."""
    canonical = resolve_retrieval_mode(mode)
    return {
        "vector": "qdrant",
        "deep": "neo4j",
        "hybrid": "qdrant+neo4j",
        "auto": "router",
    }[canonical]
