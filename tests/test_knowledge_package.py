from __future__ import annotations

import pytest

from src.knowledge_package import (
    PACKAGE_SCHEMA,
    KnowledgePackageError,
    package_digest,
    stable_chunk_id,
    validate_package,
)


def package(**changes):
    value = {
        "schema": PACKAGE_SCHEMA,
        "document_id": "doc-1",
        "version": "v1",
        "metadata": {"source_system": "CSIT"},
        "chunks": [{"content": "same content", "source_locator": "page:1"}],
        "nodes": [],
        "relationships": [],
        "publish_status": "draft",
    }
    value.update(changes)
    return value


def test_package_requires_canonical_fields_and_draft_default():
    normalized = validate_package(package())
    assert normalized["chunks"][0]["chunk_id"] == stable_chunk_id("doc-1", "v1", "same content", "page:1")
    assert normalized["publish_status"] == "draft"


@pytest.mark.parametrize("field", ["schema", "document_id", "version", "metadata", "chunks"])
def test_package_rejects_missing_required_field(field):
    value = package()
    value.pop(field)
    with pytest.raises(KnowledgePackageError):
        validate_package(value)


def test_package_digest_is_repeatable_and_content_sensitive():
    first = package_digest(package())
    assert first == package_digest(package())
    assert first != package_digest(package(chunks=[{"content": "changed", "source_locator": "page:1"}]))

