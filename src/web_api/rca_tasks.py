"""The Celery task behind POST /api/rca/v1/analyze. Runs in the search worker, which already has the primary LLM; it reads km_test through the
read-only role (KM_RCA_DSN_FILE) and answers with the comparison pack and the verified analysis. Importing this module registers the task."""
from __future__ import annotations

import logging
import os
import time

from ..report_numeric import compare, rca_service
from .tasks import celery_app

logger = logging.getLogger("km.rca")


@celery_app.task(name="tasks.rca_analyze_task", bind=True)
def rca_analyze_task(self, run_ids: list, question: str = "", owner: dict | None = None, focus: dict | None = None):
    from .rca_routes import default_connect, default_llm, default_roles
    llm_holder: dict = {}
    started = time.monotonic()
    budget = float(os.getenv("KM_RCA_TOTAL_SECONDS", "540"))  # below Celery's soft limit (600 s)

    def llm(messages):  # built on first use so a missing model setting is an 'unavailable' analysis, not a crashed task
        if "fn" not in llm_holder:
            llm_holder["fn"] = default_llm()
        left = budget - (time.monotonic() - started)
        if left < 30:
            raise TimeoutError("analysis time budget used up")
        client = getattr(llm_holder["fn"], "client", None)
        if client is not None:  # the correction round never waits longer than what is left of the budget
            client.timeout = min(client.timeout, left)
        return llm_holder["fn"](messages)

    try:
        result = rca_service.analyze(default_connect, default_roles(), llm, [str(r) for r in run_ids], question or "", focus)
    except compare.CompareError as exc:
        return {"owner": owner, "status": "failed", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - e.g. the report store is unreachable; never leak details to the page
        logger.warning("RCA analysis failed", exc_info=True)
        return {"owner": owner, "status": "failed", "detail": "分析無法完成（" + type(exc).__name__ + "）"}
    return {"owner": owner, "status": "done", **result}
