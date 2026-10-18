"""Deterministic Knowledge Package publish lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .knowledge_package import PUBLISH_STATUSES


class PublishLifecycleError(ValueError):
    """Raised when a revision cannot make a valid lifecycle transition."""


@dataclass(frozen=True)
class PackageRevision:
    package_id: str
    document_id: str
    document_version: str
    publish_status: str = "draft"
    is_current: bool = False

    def __post_init__(self) -> None:
        if self.publish_status not in PUBLISH_STATUSES:
            raise PublishLifecycleError(f"unsupported publish_status: {self.publish_status}")
        if self.is_current and self.publish_status != "published":
            raise PublishLifecycleError("only published revisions can be current")


_ALLOWED_TRANSITIONS = {
    "draft": frozenset({"ready"}),
    "ready": frozenset({"published"}),
    "published": frozenset({"superseded"}),
    "superseded": frozenset(),
}


def transition_revision(revision: PackageRevision, target_status: str) -> PackageRevision:
    """Return a validated revision transition without mutating the input."""
    if target_status not in PUBLISH_STATUSES:
        raise PublishLifecycleError(f"unsupported publish_status: {target_status}")
    if target_status not in _ALLOWED_TRANSITIONS[revision.publish_status]:
        raise PublishLifecycleError(
            f"invalid transition: {revision.publish_status} -> {target_status}"
        )
    return replace(revision, publish_status=target_status, is_current=False)


def publish_revision(
    revisions: Iterable[PackageRevision],
    *,
    document_id: str,
    package_id: str,
) -> tuple[PackageRevision, ...]:
    """Publish one ready revision and supersede the prior current revision.

    The complete result is a transaction plan for a registry/store adapter.
    Cross-store atomicity is intentionally handled by the KM-004 workstream.
    """
    current = tuple(revisions)
    targets = [r for r in current if r.package_id == package_id]
    if len(targets) != 1:
        raise PublishLifecycleError("publish target must identify exactly one revision")
    target = targets[0]
    if target.document_id != document_id:
        raise PublishLifecycleError("publish target document_id mismatch")
    if target.publish_status != "ready":
        raise PublishLifecycleError("only ready revisions can be published")

    result = []
    for revision in current:
        if revision.package_id == package_id:
            result.append(replace(revision, publish_status="published", is_current=True))
        elif revision.document_id == document_id and revision.is_current:
            result.append(replace(revision, publish_status="superseded", is_current=False))
        else:
            result.append(revision)
    return tuple(result)


def published_current(revision: PackageRevision) -> bool:
    """Whether a revision is visible to the default search contract."""
    return revision.publish_status == "published" and revision.is_current
