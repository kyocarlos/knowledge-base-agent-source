"""Technical publication coordinator used by the formal KM ingest boundary.

Qdrant and Neo4j do not share a transaction.  This coordinator therefore uses
an explicit stage/commit/rollback protocol and refuses to advertise a version
as Current until every required store has committed.  Concrete store adapters
are injected by the existing KM pipeline; this module does not create a
second ingestion path.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class PublicationError(RuntimeError):
    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(message)


class StoreWriter(Protocol):
    name: str

    def stage(self, package: Mapping[str, Any]) -> Any: ...
    def commit(self, staged: Any) -> None: ...
    def rollback(self, staged: Any) -> None: ...


@dataclass(frozen=True)
class PublicationResult:
    document_id: str
    version: str
    status: str
    committed_stores: tuple[str, ...]


class AtomicTechnicalPublisher:
    """Coordinate required store writes without delete-before-ingest."""

    def __init__(self, writers: list[StoreWriter]):
        if not writers:
            raise ValueError("at least one required store is needed")
        self.writers = tuple(writers)

    def publish(self, package: Mapping[str, Any]) -> PublicationResult:
        from .knowledge_package import validate_package

        normalized = validate_package(package)
        staged: list[tuple[StoreWriter, Any]] = []
        try:
            for writer in self.writers:
                try:
                    staged.append((writer, writer.stage(normalized)))
                except Exception as exc:
                    raise PublicationError(f"stage:{writer.name}", str(exc)) from exc

            committed: list[str] = []
            try:
                for writer, handle in staged:
                    writer.commit(handle)
                    committed.append(writer.name)
            except Exception as exc:
                raise PublicationError("commit", str(exc)) from exc
        except Exception:
            for writer, handle in reversed(staged):
                try:
                    writer.rollback(handle)
                except Exception:
                    # Rollback is best effort, but publication is never
                    # reported as successful after a partial write.
                    pass
            raise

        return PublicationResult(
            document_id=normalized["document_id"],
            version=normalized["version"],
            status="published",
            committed_stores=tuple(committed),
        )

