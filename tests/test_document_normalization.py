from __future__ import annotations

import pytest

from src.document_normalization import (
    NormalizationCatalog,
    NormalizationError,
    ResolutionStatus,
    normalize_record,
    normalize_value,
)


@pytest.fixture
def catalog() -> NormalizationCatalog:
    return NormalizationCatalog.from_dict(
        {
            "aliases": {
                "technology": {"5G NR": "NR"},
                "category": {"test report": "test_report"},
            },
            "ontology": {"category": {"test report": "test_report"}},
            "master_data": {
                "device": [
                    {
                        "canonical_id": "device-scu2050",
                        "canonical_value": "SCU2050",
                        "aliases": ["SCU-2050", "SCU 2050"],
                        "ontology_category": "device",
                    }
                ]
            },
        }
    )


def test_alias_and_master_data_resolution_preserve_provenance(catalog):
    technology = normalize_value("technology", " 5g_nr ", catalog)
    device = normalize_value("device", "SCU-2050", catalog, namespace="device")

    assert technology.status is ResolutionStatus.CANONICAL
    assert technology.canonical_value == "NR"
    assert technology.publishable is True
    assert device.canonical_id == "device-scu2050"
    assert device.canonical_value == "SCU2050"
    assert device.ontology_category == "device"
    assert device.as_dict()["provenance"]["raw_value"] == "SCU-2050"


def test_unknown_and_invalid_values_are_not_publishable(catalog):
    unknown = normalize_value("device", "SCU9999", catalog, namespace="device")
    invalid = normalize_value("device", None, catalog, namespace="device")

    assert unknown.status is ResolutionStatus.UNKNOWN
    assert unknown.canonical_value is None
    assert unknown.publishable is False
    assert invalid.status is ResolutionStatus.INVALID
    assert invalid.publishable is False


def test_ontology_mapping_resolves_without_alias_mapping():
    catalog = NormalizationCatalog.from_dict(
        {"ontology": {"document_type": {"Test Report": "test_report"}}}
    )
    result = normalize_value("document_type", "test-report", catalog)
    assert result.status is ResolutionStatus.CANONICAL
    assert result.canonical_value == "test_report"


def test_record_output_is_sorted_and_deterministic(catalog):
    first = normalize_record(
        {"z": "unknown", "technology": "5G NR", "device": "SCU2050"},
        catalog,
        namespaces={"device": "device"},
    )
    second = normalize_record(
        {"device": "SCU2050", "technology": "5G NR", "z": "unknown"},
        catalog,
        namespaces={"device": "device"},
    )

    assert list(first) == ["device", "technology", "z"]
    assert {key: value.as_dict() for key, value in first.items()} == {
        key: value.as_dict() for key, value in second.items()
    }


def test_duplicate_master_alias_fails_closed_at_catalog_creation():
    with pytest.raises(NormalizationError, match="ambiguous master-data alias"):
        NormalizationCatalog.from_dict(
            {
                "master_data": {
                    "device": [
                        {"canonical_id": "a", "canonical_value": "A", "aliases": ["same"]},
                        {"canonical_id": "b", "canonical_value": "B", "aliases": ["SAME"]},
                    ]
                }
            }
        )


def test_normalization_does_not_mutate_input(catalog):
    values = {"technology": "5G NR"}
    before = values.copy()
    normalize_record(values, catalog)
    assert values == before
