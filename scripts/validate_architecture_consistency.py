#!/usr/bin/env python3
"""Validate the public architecture claims against the current source contract."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CONTRACT = (ROOT / "docs/architecture-contract.md").read_text(encoding="utf-8")
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")


def validate() -> None:
    forbidden = ("Neo4j Vector", "Neo4j 向量", "ChromaDB")
    for claim in forbidden:
        if claim in README:
            raise SystemExit(f"stale architecture claim: {claim}")

    required_readme = ("architecture-contract.md", "Qdrant", "Neo4j", "QDRANT_URL")
    for claim in required_readme:
        if claim not in README:
            raise SystemExit(f"README missing architecture claim: {claim}")

    required_compose = (
        "qdrant:",
        "image: qdrant/qdrant:v1.13.6",
        "QDRANT_URL=http://qdrant:6333",
        "bash -ec 'echo >/dev/tcp/127.0.0.1/6333'",
    )
    for claim in required_compose:
        if claim not in COMPOSE:
            raise SystemExit(f"Compose missing Qdrant contract: {claim}")


if __name__ == "__main__":
    validate()
    print("architecture_consistency=PASS")
