"""Standalone, mock-only HTTP control plane for the first A2A rollout phase."""

from __future__ import annotations

import hashlib
import hmac

from fastapi import Depends, FastAPI, Header, HTTPException, status

from .config import BridgeConfig
from .contracts import BridgeDispatchError, TaskRecord, TestJob
from .journal import JournalConflict, TaskJournal
from .service import BridgeService
from .transport import A2ATransport, MockA2ATransport


def _control_auth(config: BridgeConfig):
    def authenticate(authorization: str = Header(default="")) -> None:
        scheme, _, token = authorization.partition(" ")
        expected = config.control_token_sha256
        if scheme.lower() != "bearer" or not token or expected is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="control token required")
        actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected.get_secret_value().lower(), actual):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid control token")

    return authenticate


def create_app(
    config: BridgeConfig | None = None,
    journal: TaskJournal | None = None,
    transport: A2ATransport | None = None,
) -> FastAPI:
    bridge_config = config or BridgeConfig.from_env()
    task_journal = journal or TaskJournal(bridge_config.journal_path)
    selected_transport = transport
    if selected_transport is None:
        if bridge_config.transport_mode == "sdk-dry-run":
            from .sdk_transport import SdkA2ATransport

            selected_transport = SdkA2ATransport()
        else:
            selected_transport = MockA2ATransport()
    bridge_service = BridgeService(
        bridge_config,
        task_journal,
        selected_transport,
    )
    authenticate = _control_auth(bridge_config)
    app = FastAPI(title="KM A2A Delegation Bridge", version="0.1.0")

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "enabled": bridge_config.enabled,
            "transport": bridge_config.transport_mode,
            "real_instrument_access": False,
        }

    @app.post("/v1/tasks", response_model=TaskRecord, status_code=status.HTTP_202_ACCEPTED)
    async def submit(job: TestJob, _: None = Depends(authenticate)):
        try:
            record, _duplicate = await bridge_service.submit(job)
            return record
        except BridgeDispatchError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"reason": exc.reason.value}) from exc
        except JournalConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="run_id_conflict") from exc

    @app.get("/v1/tasks/{environment}/{run_id}", response_model=TaskRecord)
    async def get_task(environment: str, run_id: str, _: None = Depends(authenticate)):
        record = task_journal.get(f"{environment}:{run_id}")
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")
        return record

    return app
