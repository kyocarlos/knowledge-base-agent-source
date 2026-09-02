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


class StoreConsistencyError(RuntimeError):
    """Sanitized fail-closed diagnostic for a multi-store publish attempt."""

    def __init__(
        self,
        operation: str,
        store_outcomes: dict[str, str],
        rollback_outcomes: dict[str, str],
    ) -> None:
        self.operation = operation
        self.store_outcomes = dict(store_outcomes)
        self.rollback_outcomes = dict(rollback_outcomes)
        self.partial_write = any(value == "applied" for value in store_outcomes.values())
        self.rollback_complete = all(
            value == "pass" for value in rollback_outcomes.values()
        )
        super().__init__(self._message())

    def _message(self) -> str:
        outcomes = ",".join(
            f"{name}={value}" for name, value in self.store_outcomes.items()
        )
        rollback = ",".join(
            f"{name}={value}" for name, value in self.rollback_outcomes.items()
        ) or "none"
        return (
            "store consistency failure: "
            f"operation={self.operation}; "
            f"partial_write={str(self.partial_write).lower()}; "
            f"outcomes={outcomes}; "
            f"rollback_complete={str(self.rollback_complete).lower()}; "
            f"rollback={rollback}"
        )


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
        store_outcomes: dict[str, str] = {}
        rollback_outcomes: dict[str, str] = {}
        attempted: list[tuple[str, Any, str, str, bool]] = []
        operation = "store visibility"
        failures: list[str] = []

        def apply_visibility(
            store_name: str,
            store: Any,
            target_package_id: str,
            target_status: str,
            target_current: bool,
            label: str,
        ) -> bool:
            nonlocal operation
            if store is None:
                return True
            operation = label
            key = f"{store_name}:{target_package_id}"
            attempted.append(
                (store_name, store, target_package_id, target_status, target_current)
            )
            try:
                applied = store.set_package_visibility(
                    target_package_id, target_status, target_current
                )
            except Exception:
                store_outcomes[key] = "unknown"
                failures.append(label)
                return False
            if not applied:
                store_outcomes[key] = "failed"
                attempted.pop()
                failures.append(label)
                return False
            store_outcomes[key] = "applied"
            return True

        def apply_stage(updates: list[tuple[str, Any, str, str, bool, str]]) -> None:
            failures.clear()
            for update in updates:
                apply_visibility(*update)
            if failures:
                raise StoreConsistencyError(
                    failures[0], store_outcomes, rollback_outcomes
                )

        try:
            apply_stage([
                ("qdrant", vector_store, package_id, "published", True,
                 "Qdrant package visibility"),
                ("neo4j", graph_writer, package_id, "published", True,
                 "Neo4j package visibility"),
            ])
            if prior:
                apply_stage([
                    ("qdrant", vector_store, prior["package_id"], "superseded", False,
                     "Qdrant prior revision visibility"),
                    ("neo4j", graph_writer, prior["package_id"], "superseded", False,
                     "Neo4j prior revision visibility"),
                ])
            published = self.registry.publish_knowledge_revision(
                package_id, prior and prior["package_id"]
            )
            if prior:
                self.registry.transition_knowledge_revision(
                    prior["package_id"], "superseded"
                )
            return published
        except StoreConsistencyError as exc:
            primary_error = exc
        except Exception:
            primary_error = StoreConsistencyError(
                operation, store_outcomes, rollback_outcomes
            )

        # Restore every attempted store operation in reverse order. The registry
        # is advanced only after all store updates succeed.
        for store_name, store, target_package_id, _, _ in reversed(attempted):
            original = current if target_package_id == package_id else prior
            if store is None or original is None:
                continue
            rollback_key = f"{store_name}:{target_package_id}"
            try:
                if not store.set_package_visibility(
                    target_package_id,
                    original["publish_status"],
                    original["is_current"],
                ):
                    rollback_outcomes[rollback_key] = "failed"
                else:
                    rollback_outcomes[rollback_key] = "pass"
            except Exception:
                rollback_outcomes[rollback_key] = "failed"

        raise StoreConsistencyError(operation, store_outcomes, rollback_outcomes) from primary_error
