"""Deterministic alias, master-data, and ontology normalization for WP10B.

This module is deliberately catalog-driven. It never asks an LLM to infer an
identity and never persists the result. Unknown or ambiguous values remain
non-publishable until an authoritative catalog is supplied.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class NormalizationError(ValueError):
    """Raised when the normalization catalog itself is invalid."""


class ResolutionStatus(str, Enum):
    CANONICAL = "canonical"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    INVALID = "invalid"


def _key(value: object) -> str:
    """Create a stable comparison key without changing the original value."""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"[\s_\-./]+", "", text)


@dataclass(frozen=True, slots=True)
class MasterDataRecord:
    """Authoritative identity and label for one namespace record."""

    canonical_id: str
    canonical_value: str
    aliases: tuple[str, ...] = ()
    ontology_category: str | None = None

    def __post_init__(self) -> None:
        if not self.canonical_id.strip() or not self.canonical_value.strip():
            raise NormalizationError("master-data identity and value are required")
        if any(not alias.strip() for alias in self.aliases):
            raise NormalizationError("master-data aliases must not be empty")


@dataclass(frozen=True, slots=True)
class NormalizationCatalog:
    """Immutable, validated catalog supplied by an authoritative owner."""

    aliases: Mapping[str, Mapping[str, str]]
    master_data: Mapping[str, tuple[MasterDataRecord, ...]]
    ontology: Mapping[str, Mapping[str, str]]

    def __post_init__(self) -> None:
        for field, values in self.aliases.items():
            _validate_lookup(field, values)
        for field, values in self.ontology.items():
            _validate_lookup(field, values)
        for namespace, records in self.master_data.items():
            seen_ids: set[str] = set()
            seen_aliases: dict[str, str] = {}
            for record in records:
                record_key = _key(record.canonical_id)
                if record_key in seen_ids:
                    raise NormalizationError(f"duplicate master-data identity in {namespace}")
                seen_ids.add(record_key)
                for alias in (record.canonical_id, record.canonical_value, *record.aliases):
                    alias_key = _key(alias)
                    previous = seen_aliases.get(alias_key)
                    if previous is not None and previous != record.canonical_id:
                        raise NormalizationError(f"ambiguous master-data alias in {namespace}")
                    seen_aliases[alias_key] = record.canonical_id

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "NormalizationCatalog":
        """Build a catalog from plain data without inventing missing records."""
        raw_master = data.get("master_data", {})
        if not isinstance(raw_master, Mapping):
            raise NormalizationError("master_data must be an object")
        master: dict[str, tuple[MasterDataRecord, ...]] = {}
        for namespace, raw_records in raw_master.items():
            if not isinstance(raw_records, (list, tuple)):
                raise NormalizationError("master-data namespace must be a list")
            records: list[MasterDataRecord] = []
            for raw in raw_records:
                if not isinstance(raw, Mapping):
                    raise NormalizationError("master-data record must be an object")
                aliases = raw.get("aliases", ())
                if not isinstance(aliases, (list, tuple)):
                    raise NormalizationError("master-data aliases must be a list")
                records.append(
                    MasterDataRecord(
                        canonical_id=str(raw.get("canonical_id", "")),
                        canonical_value=str(raw.get("canonical_value", "")),
                        aliases=tuple(str(alias) for alias in aliases),
                        ontology_category=(
                            str(raw["ontology_category"])
                            if raw.get("ontology_category") is not None
                            else None
                        ),
                    )
                )
            master[str(namespace)] = tuple(records)
        return cls(
            aliases=_freeze_lookup(data.get("aliases", {}), "aliases"),
            master_data=MappingProxyType(master),
            ontology=_freeze_lookup(data.get("ontology", {}), "ontology"),
        )


@dataclass(frozen=True, slots=True)
class NormalizedValue:
    field: str
    raw_value: object
    normalized_value: str
    status: ResolutionStatus
    canonical_id: str | None = None
    canonical_value: str | None = None
    ontology_category: str | None = None

    @property
    def publishable(self) -> bool:
        return self.status is ResolutionStatus.CANONICAL

    def as_dict(self) -> dict[str, object]:
        return {
            "field": self.field,
            "raw_value": self.raw_value,
            "normalized_value": self.normalized_value,
            "status": self.status.value,
            "canonical_id": self.canonical_id,
            "canonical_value": self.canonical_value,
            "ontology_category": self.ontology_category,
            "publishable": self.publishable,
            "provenance": {
                "raw_value": self.raw_value,
                "normalized_value": self.normalized_value,
                "resolution": self.status.value,
                "canonical_id": self.canonical_id,
                "canonical_value": self.canonical_value,
            },
        }


def _validate_lookup(name: str, values: Mapping[str, str]) -> None:
    seen: dict[str, str] = {}
    for raw, canonical in values.items():
        if not str(raw).strip() or not str(canonical).strip():
            raise NormalizationError(f"empty {name} mapping is not allowed")
        key = _key(raw)
        previous = seen.get(key)
        if previous is not None and previous != str(canonical):
            raise NormalizationError(f"ambiguous {name} alias")
        seen[key] = str(canonical)


def _freeze_lookup(raw: object, label: str) -> Mapping[str, Mapping[str, str]]:
    if not isinstance(raw, Mapping):
        raise NormalizationError(f"{label} must be an object")
    result: dict[str, Mapping[str, str]] = {}
    for field, values in raw.items():
        if not isinstance(values, Mapping):
            raise NormalizationError(f"{label} field must be an object")
        copied = {str(key): str(value) for key, value in values.items()}
        _validate_lookup(str(field), copied)
        result[str(field)] = MappingProxyType(copied)
    return MappingProxyType(result)


def _lookup_mapping(mappings: Mapping[str, str], value: str) -> str | None:
    key = _key(value)
    matches = {canonical for raw, canonical in mappings.items() if _key(raw) == key}
    if len(matches) > 1:
        return None
    return next(iter(matches), None)


def _lookup_alias(field: str, value: str, catalog: NormalizationCatalog) -> str | None:
    return _lookup_mapping(catalog.aliases.get(field, {}), value)


def normalize_value(
    field: str, raw_value: object, catalog: NormalizationCatalog, *, namespace: str | None = None
) -> NormalizedValue:
    """Resolve one value using explicit aliases/master data only."""
    if not isinstance(field, str) or not field.strip() or raw_value is None:
        return NormalizedValue(str(field), raw_value, "", ResolutionStatus.INVALID)
    normalized = _key(raw_value)
    if not normalized:
        return NormalizedValue(field, raw_value, normalized, ResolutionStatus.INVALID)

    if namespace is not None:
        records = catalog.master_data.get(namespace, ())
        matches = [
            record
            for record in records
            if any(_key(candidate) == normalized for candidate in (
                record.canonical_id, record.canonical_value, *record.aliases
            ))
        ]
        if len(matches) > 1:
            return NormalizedValue(field, raw_value, normalized, ResolutionStatus.AMBIGUOUS)
        if matches:
            record = matches[0]
            return NormalizedValue(
                field,
                raw_value,
                normalized,
                ResolutionStatus.CANONICAL,
                record.canonical_id,
                record.canonical_value,
                record.ontology_category,
            )

    canonical = _lookup_alias(field, str(raw_value), catalog)
    if canonical is None:
        canonical = _lookup_mapping(catalog.ontology.get(field, {}), str(raw_value))
    if canonical is not None:
        category = _lookup_alias("category", canonical, catalog)
        if category is None:
            category = _lookup_mapping(catalog.ontology.get("category", {}), canonical)
        return NormalizedValue(
            field, raw_value, normalized, ResolutionStatus.CANONICAL, None, canonical, category
        )
    return NormalizedValue(field, raw_value, normalized, ResolutionStatus.UNKNOWN)


def normalize_record(
    values: Mapping[str, object], catalog: NormalizationCatalog, *, namespaces: Mapping[str, str] | None = None
) -> dict[str, NormalizedValue]:
    """Normalize fields in sorted order for deterministic, non-mutating output."""
    if not isinstance(values, Mapping):
        raise NormalizationError("values must be an object")
    namespace_map = namespaces or {}
    return {
        field: normalize_value(field, values[field], catalog, namespace=namespace_map.get(field))
        for field in sorted(values)
    }
