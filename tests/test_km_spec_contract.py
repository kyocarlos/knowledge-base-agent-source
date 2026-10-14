from __future__ import annotations

import pytest

from src.km_spec_contract import KMSpecContractError, build_routing_plan, validate_metadata


def metadata(**overrides):
    value = {
        "document_id": "DOC-001",
        "document_version": "1.0.0",
        "document_type": "test_report",
        "source_system": "CSIT",
        "access_roles": ["RD"],
        "visibility": "project",
        "publish_status": "published",
        "approval_status": "approved",
        "is_current": True,
    }
    value.update(overrides)
    return value


def test_missing_metadata_fails_closed():
    with pytest.raises(KMSpecContractError) as exc:
        validate_metadata({})
    assert exc.value.code == "metadata_missing"
    assert "document_id" in exc.value.fields


@pytest.mark.parametrize(
    "overrides",
    [{"publish_status": "draft", "is_current": True}, {"publish_status": "published", "approval_status": "pending"}],
)
def test_non_publishable_lifecycle_is_rejected(overrides):
    with pytest.raises(KMSpecContractError):
        validate_metadata(metadata(**overrides))


def test_draft_routes_to_no_persistence_destinations():
    plan = build_routing_plan(metadata(publish_status="draft", approval_status="pending", is_current=False), artifact_type="report")
    assert plan.indexable is False
    assert plan.destinations == ()
    assert plan.published_only is True


def test_published_report_routes_to_neo4j_and_qdrant():
    plan = build_routing_plan(metadata(), artifact_type="report")
    assert plan.indexable is True
    assert plan.destinations == ("neo4j", "qdrant")
    assert plan.decision_id == build_routing_plan(metadata(), artifact_type="report").decision_id


def test_timeseries_never_routes_to_qdrant():
    plan = build_routing_plan(metadata(), artifact_type="timeseries")
    assert plan.destinations == ("timescaledb",)
    assert "qdrant" not in plan.destinations


def test_unknown_route_fails_closed():
    with pytest.raises(KMSpecContractError) as exc:
        build_routing_plan(metadata(), artifact_type="booking")
    assert exc.value.code == "route_unknown"
