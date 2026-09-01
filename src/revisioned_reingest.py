"""Non-destructive re-ingest orchestration for versioned knowledge packages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .knowledge_lifecycle import KnowledgeLifecycle


@dataclass(frozen=True)
class ReingestResult:
    """Outcome of one processing/indexing attempt."""

    package_id: str
    status: str
    published: bool
    current: bool
    error: str | None = None


def reingest_revision(
    lifecycle: KnowledgeLifecycle,
    package_id: str,
    process_and_index: Callable[[], Any],
    *,
    vector_store=None,
    graph_writer=None,
) -> ReingestResult:
    """Process a revision before publishing it, without removing the current one.

    ``process_and_index`` is responsible for writing the revision's draft data to
    the existing stores.  A false return or exception is a failed attempt and
    leaves the revision unpublished.  The same package can then be retried.
    """
    revision = lifecycle.get(package_id)
    if not revision:
        raise KeyError(package_id)
    if revision["publish_status"] not in {"draft", "ready"}:
        raise ValueError("only draft or ready revisions can be re-ingested")

    try:
        result = process_and_index()
        if result is False:
            raise RuntimeError("revision processing/indexing failed")
        if revision["publish_status"] == "draft":
            lifecycle.transition(package_id, "ready")
        published = lifecycle.publish(
            package_id,
            vector_store=vector_store,
            graph_writer=graph_writer,
        )
        return ReingestResult(
            package_id=package_id,
            status=published["publish_status"],
            published=True,
            current=bool(published["is_current"]),
        )
    except Exception as exc:
        current = lifecycle.get(package_id) or revision
        return ReingestResult(
            package_id=package_id,
            status=current["publish_status"],
            published=False,
            current=bool(current["is_current"]),
            error=str(exc),
        )
