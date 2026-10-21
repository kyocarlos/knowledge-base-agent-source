"""Read-only CSIT browsing proxy for the KM stage environment.

Credentials and cookies stay inside the process. This router exposes only the
approved GET contract and never forwards CSIT write operations.
"""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..csit import CsitReadOnlyClient, CsitRequestError, load_contract
from ..test_reports.auth import authenticate_csit_reader, csit_download_ticket_filename, safe_csit_filename


router = APIRouter(
    prefix="/api/csit",
    tags=["CSIT read-only"],
    dependencies=[Depends(authenticate_csit_reader)],
)
_client: CsitReadOnlyClient | None = None
_client_lock = Lock()


def run_csit_assistant_query(query: str) -> str:
    """Run the approved CSIT read chain for the authenticated chat proxy."""
    from ..csit.assistant import answer_csit_query

    return answer_csit_query(_client_or_503(), query)


def _enabled() -> bool:
    return os.getenv("CSIT_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def _secret_value(env_name: str, file_env_name: str) -> str:
    """Prefer a mounted secret file; retain env fallback for local staging."""
    file_path = os.getenv(file_env_name, "").strip()
    if file_path:
        try:
            return Path(file_path).read_text(encoding="utf-8").strip()
        except OSError:
            return ""
    return os.getenv(env_name, "")


def _client_or_503() -> CsitReadOnlyClient:
    global _client
    if not _enabled():
        raise HTTPException(status_code=503, detail="CSIT read-only integration is disabled")
    with _client_lock:
        if _client is None:
            base_url = os.getenv("CSIT_BASE_URL", "").strip()
            username = _secret_value("CSIT_USERNAME", "CSIT_USERNAME_FILE")
            password = _secret_value("CSIT_PASSWORD", "CSIT_PASSWORD_FILE")
            contract_path = Path(os.getenv("CSIT_CONTRACT_PATH", "config/csit_api_contract.json"))
            ca_cert = os.getenv("CSIT_CA_CERT", "").strip()
            if not base_url or not username or not password:
                raise HTTPException(status_code=503, detail="CSIT integration configuration is incomplete")
            if not contract_path.exists():
                raise HTTPException(status_code=503, detail="CSIT API contract is unavailable")
            try:
                _client = CsitReadOnlyClient(
                    base_url,
                    load_contract(contract_path),
                    username=username,
                    password=password,
                    timeout=float(os.getenv("CSIT_TIMEOUT_SECONDS", "20")),
                    verify=ca_cert or True,
                )
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=503, detail=f"CSIT client configuration failed: {type(exc).__name__}") from None
    return _client


def _get(path: str, *, path_params: dict[str, object] | None = None, query: dict[str, object] | None = None):
    try:
        return _client_or_503().get(path, path_params=path_params, query=query)
    except CsitRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except KeyError:
        raise HTTPException(status_code=500, detail="CSIT endpoint is not present in the approved contract") from None


@router.get("/modules/enabled")
def enabled_modules():
    return _get("/api/modules/enabled")


@router.get("/modules/{module_code}/records")
def module_records(module_code: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
    return _get("/api/modules/{moduleCode}/records", path_params={"moduleCode": module_code}, query={"page": page, "pageSize": page_size})


@router.get("/records/{record_id}")
def record_detail(record_id: str):
    return _get("/api/records/{id}", path_params={"id": record_id})


@router.get("/records/{record_id}/cases")
def record_cases(record_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
    return _get("/api/records/{recordId}/cases", path_params={"recordId": record_id}, query={"page": page, "pageSize": page_size})


@router.get("/cases/{case_id}")
def case_detail(case_id: str):
    return _get("/api/cases/{id}", path_params={"id": case_id})


@router.get("/cases/{case_id}/files")
def case_files(case_id: str):
    return _get("/api/cases/{caseId}/files", path_params={"caseId": case_id})


@router.get("/cases/{case_id}/tasks")
def case_tasks(case_id: str, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100)):
    return _get("/api/cases/{caseId}/tasks", path_params={"caseId": case_id}, query={"page": page, "pageSize": page_size})


@router.get("/tasks/{task_id}")
def task_detail(task_id: str):
    return _get("/api/tasks/{id}", path_params={"id": task_id})


@router.get("/tasks/{task_id}/files")
def task_files(task_id: str):
    return _get("/api/tasks/{taskId}/files", path_params={"taskId": task_id})


@router.get("/files/{file_id}/download")
def download_file(file_id: str, ticket: str = ""):
    client = _client_or_503()
    try:
        upstream = client.download("/api/files/{fileId}/download", path_params={"fileId": file_id})
        max_bytes = int(os.getenv("CSIT_MAX_DOWNLOAD_BYTES", str(100 * 1024 * 1024)))
        if len(upstream.content) > max_bytes:
            raise HTTPException(status_code=413, detail="CSIT file exceeds the configured download limit")
        media_type = upstream.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
        ticket_filename = csit_download_ticket_filename(file_id, ticket)
        filename = ticket_filename or safe_csit_filename(
            upstream.headers.get("content-disposition", "").split("filename=", 1)[-1],
            f"csit-{file_id}.bin",
        )
        return Response(
            content=upstream.content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except CsitRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    finally:
        if "upstream" in locals():
            upstream.close()
