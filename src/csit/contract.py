"""Validated, generated CSIT REST contract metadata."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CsitEndpoint:
    category: str
    controller: str
    method: str
    path: str
    parameters: str
    response: str
    authorization: str
    description: str
    integration_stage: str
    read_only_allowed: bool

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CsitEndpoint":
        method = str(value["method"]).upper()
        read_only_allowed = method == "GET"
        if bool(value.get("read_only_allowed", read_only_allowed)) != read_only_allowed:
            raise ValueError(f"read_only_allowed mismatch for {value.get('path')}")
        return cls(
            category=str(value["category"]),
            controller=str(value["controller"]),
            method=method,
            path=str(value["path"]),
            parameters=str(value.get("parameters", "")),
            response=str(value.get("response", "")),
            authorization=str(value.get("authorization", "")),
            description=str(value.get("description", "")),
            integration_stage=str(value["integration_stage"]),
            read_only_allowed=read_only_allowed,
        )


@dataclass(frozen=True, slots=True)
class CsitContract:
    schema: str
    source_file: str
    source_sha256: str
    endpoints: tuple[CsitEndpoint, ...]
    known_gaps: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CsitContract":
        endpoints = tuple(CsitEndpoint.from_dict(item) for item in value["endpoints"])
        if not endpoints:
            raise ValueError("CSIT contract has no endpoints")
        return cls(
            schema=str(value["schema"]),
            source_file=str(value["source_file"]),
            source_sha256=str(value["source_sha256"]),
            endpoints=endpoints,
            known_gaps=tuple(str(item) for item in value.get("known_gaps", [])),
        )

    def endpoint(self, path: str, method: str = "GET") -> CsitEndpoint:
        method = method.upper()
        for endpoint in self.endpoints:
            if endpoint.path == path and endpoint.method == method:
                return endpoint
        raise KeyError(f"CSIT endpoint not mapped: {method} {path}")


def load_contract(path: str | Path) -> CsitContract:
    """Load and validate a generated contract without contacting CSIT."""

    return CsitContract.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
