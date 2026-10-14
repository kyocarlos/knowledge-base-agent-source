"""Canonical CSIT Integration v1 callback payload construction."""


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
    return payload
