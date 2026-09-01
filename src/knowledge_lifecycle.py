"""Durable publish lifecycle for versioned knowledge packages."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from .ingest_registry import IngestRegistry
from .knowledge_package import PUBLISH_STATUSES


ALLOWED_TRANSITIONS = {
    "draft": {"ready"},
    "ready": {"published"},
    "published": {"superseded"},
    "superseded": set(),
}


class LifecycleConflict(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KnowledgeLifecycle:
    """Own revision state and coordinate metadata updates across stores."""

    def __init__(self, registry: IngestRegistry | None = None):
        self.registry = registry or IngestRegistry()
        self.registry.initialize_knowledge_revisions()

    def register(self, metadata: dict[str, Any]) -> dict[str, Any]:
        required = ("package_id", "document_id", "document_version")
        if any(not str(metadata.get(key, "")).strip() for key in required):
            raise ValueError("package_id, document_id and document_version are required")
        return self.registry.register_knowledge_revision(metadata)

    def get(self, package_id: str) -> dict[str, Any] | None:
        return self.registry.find_knowledge_revision(package_id)

    def transition(self, package_id: str, target: str) -> dict[str, Any]:
        if target not in PUBLISH_STATUSES or target == "draft":
            raise ValueError("target must be ready, published or superseded")
        current = self.get(package_id)
        if not current:
            raise KeyError(package_id)
        if target not in ALLOWED_TRANSITIONS.get(current["publish_status"], set()):
            raise LifecycleConflict(
                f"invalid lifecycle transition: {current['publish_status']} -> {target}"
            )
        return self.registry.transition_knowledge_revision(package_id, target)

    def publish(self, package_id: str, *, vector_store=None, graph_writer=None) -> dict[str, Any]:
        """Publish only after stores can be updated; leave the prior current revision intact on failure."""
        current = self.get(package_id)
        if not current:
            raise KeyError(package_id)
        if current["publish_status"] != "ready":
            raise LifecycleConflict("only ready revisions can be published")

        prior = self.registry.find_current_knowledge_revision(
            current["document_id"], exclude_package_id=package_id
        )
        try:
            if vector_store is not None and not vector_store.set_package_visibility(
                package_id, "published", True
            ):
                raise RuntimeError("Qdrant package visibility update failed")
            if graph_writer is not None and not graph_writer.set_package_visibility(
                package_id, "published", True
            ):
                raise RuntimeError("Neo4j package visibility update failed")
            if prior:
                if vector_store is not None and not vector_store.set_package_visibility(
                    prior["package_id"], "superseded", False
                ):
                    raise RuntimeError("Qdrant prior revision update failed")
                if graph_writer is not None and not graph_writer.set_package_visibility(
                    prior["package_id"], "superseded", False
                ):
                    raise RuntimeError("Neo4j prior revision update failed")
            published = self.registry.publish_knowledge_revision(package_id, prior and prior["package_id"])
            if prior:
                self.registry.transition_knowledge_revision(prior["package_id"], "superseded")
            return published
        except Exception:
            # Restore metadata if a later store update fails. The registry is
            # advanced only after all store updates succeed.
            if vector_store is not None:
                vector_store.set_package_visibility(package_id, current["publish_status"], current["is_current"])
                if prior:
                    vector_store.set_package_visibility(prior["package_id"], prior["publish_status"], prior["is_current"])
            if graph_writer is not None:
                graph_writer.set_package_visibility(package_id, current["publish_status"], current["is_current"])
                if prior:
                    graph_writer.set_package_visibility(prior["package_id"], prior["publish_status"], prior["is_current"])
            raise
