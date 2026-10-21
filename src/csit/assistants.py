"""CSIT zone AI assistants: a data-driven catalogue plus real readiness probes.

An assistant whose requirements are not met stays visible but is marked pending and says what is missing; it never answers
from invented data. The report query engine is not implemented yet, so ``query_engine`` stays unmet until it is.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REGISTRY_ENV = "KM_CSIT_ASSISTANTS_FILE"
# The catalogue ships next to the code: a data zone mounts its own /app/config over the image, so a file there would be hidden.
# KM_CSIT_ASSISTANTS_FILE overrides it, and config/csit_assistants.json (when present) overrides the packaged default.
DEFAULT_REGISTRY = Path(__file__).with_name("assistants.json")
CONFIG_REGISTRY = Path(__file__).resolve().parents[2] / "config" / "csit_assistants.json"
PROBE_TIMEOUT_SECONDS = 3
READINESS_TTL_SECONDS = 30.0
_TABLE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")
# Engines that exist in code. An assistant naming an engine that is not here can never become ready.
ENGINES_IMPLEMENTED: frozenset[str] = frozenset()

_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def load_registry(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Assistant definitions; a missing or broken file means no assistants, never a failed page."""
    target = Path(path or os.getenv(REGISTRY_ENV) or (CONFIG_REGISTRY if CONFIG_REGISTRY.exists() else DEFAULT_REGISTRY))
    try:
        items = json.loads(target.read_text(encoding="utf-8"))["assistants"]
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("CSIT assistant catalogue is unavailable: %s", target)
        return []
    return [item for item in items if isinstance(item, dict) and re.fullmatch(r"[a-z][a-z0-9_]{1,40}", str(item.get("id", "")))]


def get_assistant(assistant_id: str) -> dict[str, Any] | None:
    return next((item for item in load_registry() if item["id"] == assistant_id), None)


def _count_rows(dsn: str, table: str) -> int:
    import psycopg
    from psycopg import sql

    parts = table.split(".")
    with psycopg.connect(dsn, connect_timeout=PROBE_TIMEOUT_SECONDS) as connection:
        connection.read_only = True
        return connection.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(*parts))).fetchone()[0]


def probe(requirement: dict[str, Any], engine: str = "") -> dict[str, Any]:
    """One requirement checked against the running system; ``reason`` is a code, never a connection detail."""
    result = {"id": requirement.get("id", ""), "label": requirement.get("label", ""), "ok": False, "reason": "unknown_type"}
    kind = requirement.get("type")
    if kind == "engine_flag":
        implemented = engine in ENGINES_IMPLEMENTED
        result.update(ok=implemented, reason="ok" if implemented else "not_implemented")
    elif kind == "postgres_table":
        table = str(requirement.get("table", ""))
        dsn = os.getenv(str(requirement.get("dsn_env", "")), "").strip()
        if not _TABLE.match(table):
            result["reason"] = "invalid_table"
        elif not dsn:
            result["reason"] = "not_configured"
        else:
            try:
                rows = _count_rows(dsn, table)
                enough = rows >= int(requirement.get("min_rows", 1))
                result.update(ok=enough, reason="ok" if enough else "no_rows")
            except Exception as exc:  # noqa: BLE001 - report the class only, the message may carry connection details
                logger.warning("CSIT assistant probe %s failed: %s", requirement.get("id"), type(exc).__name__)
                result["reason"] = "unreachable"
    return result


def readiness(assistant: dict[str, Any], *, use_cache: bool = True) -> dict[str, Any]:
    cached = _cache.get(assistant["id"])
    if use_cache and cached and time.monotonic() - cached[0] < READINESS_TTL_SECONDS:
        return cached[1]
    requirements = [probe(item, str(assistant.get("engine", ""))) for item in assistant.get("requires", [])]
    state = {"status": "ready" if requirements and all(r["ok"] for r in requirements) else "pending_data", "requirements": requirements}
    _cache[assistant["id"]] = (time.monotonic(), state)
    return state


REASON_TEXT = {
    "not_configured": "尚未設定連線",
    "unreachable": "無法連線",
    "no_rows": "資料表沒有資料",
    "not_implemented": "尚未實作",
    "invalid_table": "資料表設定不合法",
    "unknown_type": "不支援的條件類型",
}


def pending_answer(assistant: dict[str, Any], state: dict[str, Any]) -> str:
    missing = [f"- {r['label']}：{REASON_TEXT.get(r['reason'], r['reason'])}" for r in state["requirements"] if not r["ok"]]
    examples = "".join(f"\n- {text}" for text in assistant.get("examples", []))
    return (f"「{assistant['name']}」已加入 CSIT 知識專區，但目前還不能回答報告數據問題，因為下列條件尚未滿足：\n"
            + "\n".join(missing)
            + (f"\n\n條件滿足後，可以這樣問：{examples}" if examples else "")
            + "\n\n在此之前我不會用推測的數字回答。")


def answer(assistant: dict[str, Any], question: str) -> dict[str, Any]:
    state = readiness(assistant, use_cache=False)
    if state["status"] != "ready":
        return {"status": "pending_data", "answer": pending_answer(assistant, state), "readiness": state}
    return {"status": "error", "answer": "助手已就緒，但沒有對應的查詢引擎。", "readiness": state}
