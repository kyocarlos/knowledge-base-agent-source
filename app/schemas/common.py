"""Shared response and error contracts."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict


T = TypeVar("T")


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] | None = None


class ApiResponse(BaseModel, Generic[T]):
    model_config = ConfigDict(extra="forbid")

    data: T | None = None
    error: ApiError | None = None
    trace_id: str


class HealthData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    live: bool
    ready: bool | None


class VersionData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service: str
    version: str
    environment: str
    commit: str | None
    release_id: str | None
    image_digest: str | None
    build_timestamp: str | None
