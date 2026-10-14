import pytest
from types import SimpleNamespace

from src.publish_lifecycle import (
    PackageRevision,
    PublishLifecycleError,
    publish_revision,
    published_current,
    transition_revision,
)
from src.vector_store import VectorStore


def revision(package_id, version, status="draft", current=False):
    return PackageRevision(package_id, "doc-1", version, status, current)


def test_draft_ready_published_superseded_lifecycle():
    draft = revision("p1", "1.0.0")
    ready = transition_revision(draft, "ready")
    published = transition_revision(ready, "published")
    published = PackageRevision(published.package_id, published.document_id, published.document_version, "published", True)
    assert published_current(published)
    superseded = transition_revision(published, "superseded")
    assert superseded.publish_status == "superseded"
    assert not superseded.is_current


def test_publish_makes_new_revision_current_and_supersedes_old():
    revisions = (
        revision("p1", "1.0.0", "published", True),
        revision("p2", "2.0.0", "ready"),
    )
    result = publish_revision(revisions, document_id="doc-1", package_id="p2")
    assert result[0].publish_status == "superseded"
    assert result[0].is_current is False
    assert result[1].publish_status == "published"
    assert result[1].is_current is True


def test_publish_requires_ready_target_and_matching_document():
    with pytest.raises(PublishLifecycleError):
        publish_revision((revision("p1", "1.0.0"),), document_id="doc-1", package_id="p1")
    with pytest.raises(PublishLifecycleError):
        publish_revision((revision("p1", "1.0.0", "ready"),), document_id="doc-2", package_id="p1")


def test_invalid_transition_is_rejected():
    with pytest.raises(PublishLifecycleError):
        transition_revision(revision("p1", "1.0.0"), "published")


def test_draft_and_superseded_revisions_are_not_search_visible():
    assert not published_current(revision("p1", "1.0.0"))
    assert not published_current(revision("p2", "2.0.0", "superseded"))


def test_vector_search_defaults_to_published_current_filter():
    captured = {}
    def query_points(**kwargs):
        captured["filter"] = kwargs["query_filter"]
        return SimpleNamespace(points=[])

    store = VectorStore.__new__(VectorStore)
    store.available = True
    store.client = SimpleNamespace(query_points=query_points)
    store.encode = lambda texts: [[0.0]]

    assert store.search("query") == []
    conditions = captured["filter"].must
    assert {condition.key for condition in conditions[:2]} == {"publish_status", "is_current"}


def test_vector_search_can_explicitly_bypass_visibility_for_admin_tools():
    captured = {}
    def query_points(**kwargs):
        captured["filter"] = kwargs.get("query_filter")
        return SimpleNamespace(points=[])

    store = VectorStore.__new__(VectorStore)
    store.available = True
    store.client = SimpleNamespace(query_points=query_points)
    store.encode = lambda texts: [[0.0]]

    assert store.search("query", published_only=False) == []
    assert captured["filter"] is None
