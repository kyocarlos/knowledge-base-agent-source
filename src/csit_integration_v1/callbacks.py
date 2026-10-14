"""Canonical CSIT Integration v1 callback payload construction."""

import json
from functools import lru_cache
from pathlib import Path
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_FILES={
    "Processing":"callback-processing.schema.json",
    "Completed":"callback-completed.schema.json",
    "Failed":"callback-failed.schema.json",
}

@lru_cache(maxsize=3)
def _validator(status):
    path=Path(__file__).resolve().parents[2]/"contracts/csit-km-integration-v1"/SCHEMA_FILES[status]
    return Draft202012Validator(json.loads(path.read_text()),format_checker=FormatChecker())


def build_callback_payload(job, status, error=None):
    """Build the exact wire payload from a persisted job transition."""
    updated_at = job["updated_at"].isoformat()
    payload = {
        "jobId": str(job["job_id"]),
        "sourceSystem": job["source_system"],
        "documentId": str(job["document_id"]),
        "version": job["version"],
        "status": status,
        "timestamps": {"updatedAt": updated_at},
    }
    if status == "Processing":
        # The processing transition time, not a historical first-start time.
        payload["timestamps"]["startedAt"] = updated_at
    elif status == "Completed":
        payload["timestamps"]["completedAt"] = job["completed_at"].isoformat()
    elif status == "Failed":
        payload["timestamps"]["failedAt"] = job["last_error_at"].isoformat()
        if error is None:
            raise ValueError("Failed callback requires an error")
        payload["error"] = {"code": error.code, "message": error.message}
    else:
        raise ValueError("unsupported callback status")
    _validator(status).validate(payload)
    return payload
