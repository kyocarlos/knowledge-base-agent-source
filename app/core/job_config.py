"""Typed configuration and state contract for background jobs."""

from dataclasses import dataclass
from enum import StrEnum
import os


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class JobConfig:
    max_concurrent_processing: int = 2
    processing_lock_ttl_seconds: int = 600
    result_ttl_seconds: int = 3600
    soft_time_limit_seconds: int = 600
    time_limit_seconds: int = 720
    max_retries: int = 3
    retry_countdown_seconds: int = 5
    default_queue: str = "default"
    document_queue: str = "document"
    indexing_queue: str = "indexing"
    beat_enabled: bool = False

    @classmethod
    def from_env(cls) -> "JobConfig":
        def integer(name: str, default: int, minimum: int = 0) -> int:
            raw = os.getenv(name)
            value = default if raw in (None, "") else int(raw)
            if value < minimum:
                raise ValueError(f"{name} must be >= {minimum}")
            return value

        def boolean(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw in (None, ""):
                return default
            normalized = raw.strip().lower()
            if normalized not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError(f"{name} must be a boolean")
            return normalized in {"true", "1", "yes"}

        return cls(
            max_concurrent_processing=integer("KB_MAX_CONCURRENT_PROCESSING", 2, 1),
            processing_lock_ttl_seconds=integer("KB_PROCESSING_LOCK_TTL_SECONDS", 600, 1),
            result_ttl_seconds=integer("KB_JOB_RESULT_TTL_SECONDS", 3600, 1),
            soft_time_limit_seconds=integer("KB_JOB_SOFT_TIME_LIMIT_SECONDS", 600, 1),
            time_limit_seconds=integer("KB_JOB_TIME_LIMIT_SECONDS", 720, 1),
            max_retries=integer("KB_JOB_MAX_RETRIES", 3, 0),
            retry_countdown_seconds=integer("KB_JOB_RETRY_COUNTDOWN_SECONDS", 5, 0),
            default_queue=os.getenv("KB_DEFAULT_QUEUE", "default"),
            document_queue=os.getenv("KB_DOCUMENT_QUEUE", "document"),
            indexing_queue=os.getenv("KB_INDEXING_QUEUE", "indexing"),
            beat_enabled=boolean("KB_CELERY_BEAT_ENABLED", False),
        )


JOB_CONFIG = JobConfig.from_env()
