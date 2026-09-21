from __future__ import annotations

import pytest

from src.lifecycle import AtomicTechnicalPublisher, PublicationError


class Writer:
    def __init__(self, name, fail_stage=False, fail_commit=False):
        self.name = name
        self.fail_stage = fail_stage
        self.fail_commit = fail_commit
        self.staged = []
        self.committed = []
        self.rolled_back = []

    def stage(self, package):
        if self.fail_stage:
            raise RuntimeError("stage failed")
        token = (self.name, package["version"])
        self.staged.append(token)
        return token

    def commit(self, token):
        if self.fail_commit:
            raise RuntimeError("commit failed")
        self.committed.append(token)

    def rollback(self, token):
        self.rolled_back.append(token)


def package():
    return {
        "schema": "ai_km_knowledge_v1", "document_id": "doc-1", "version": "v2",
        "metadata": {}, "chunks": [{"content": "v2"}], "nodes": [],
        "relationships": [], "publish_status": "draft",
    }


def test_all_required_stores_commit_before_published():
    qdrant, neo4j = Writer("qdrant"), Writer("neo4j")
    result = AtomicTechnicalPublisher([qdrant, neo4j]).publish(package())
    assert result.status == "published"
    assert result.committed_stores == ("qdrant", "neo4j")


def test_store_failure_rolls_back_and_never_reports_published():
    qdrant, neo4j = Writer("qdrant"), Writer("neo4j", fail_commit=True)
    with pytest.raises(PublicationError):
        AtomicTechnicalPublisher([qdrant, neo4j]).publish(package())
    assert qdrant.committed == [("qdrant", "v2")]
    assert qdrant.rolled_back == [("qdrant", "v2")]
    assert neo4j.rolled_back == [("neo4j", "v2")]

