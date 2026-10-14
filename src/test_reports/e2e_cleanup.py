"""Run-scoped cleanup service for the isolated WP0 write E2E namespace."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .registry import SubmissionRegistry
from ..ingest_registry import IngestRegistry


SAFE_TEST_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
ACTIVE_STATUSES = {"queued", "upload_saved", "converting", "converted", "extracting", "writing_neo4j", "writing_qdrant", "refreshing_index", "approved"}


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_path(root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_symlink() or not _within(root, candidate):
        raise ValueError(f"cleanup path outside allowed root: {candidate}")
    return candidate


def _redis_client():
    import redis
    return redis.from_url(os.getenv("REDIS_URL") or os.getenv("CELERY_BROKER_URL") or "redis://redis:6379/0")


def _allowed_test_run_id(test_run_id: str) -> bool:
    prefix = os.getenv("KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX", "").strip()
    return bool(prefix and SAFE_TEST_RUN_ID.fullmatch(test_run_id) and test_run_id.startswith(prefix))


def _task_state(task_id: str) -> dict | None:
    from ..web_api.tasks import get_ingest_task_state
    return get_ingest_task_state(task_id)


def _delete_task_state(task_id: str, state: dict | None) -> None:
    from ..web_api.tasks import INGEST_FILE_HASH_INDEX_KEY, INGEST_TASK_INDEX_KEY, _ingest_task_key
    client = _redis_client()
    if state and state.get("file_hash"):
        client.hdel(INGEST_FILE_HASH_INDEX_KEY, state["file_hash"])
    client.delete(_ingest_task_key(task_id))
    client.zrem(INGEST_TASK_INDEX_KEY, task_id)


def _report_items(run_id: str) -> list[dict]:
    return SubmissionRegistry().find_by_run_any_environment(run_id)


def _ingest_items(run_id: str) -> list[dict]:
    return IngestRegistry().find_by_run(run_id)


def _file_targets(items: list[dict], ingest_items: list[dict]) -> list[Path]:
    targets: list[Path] = []
    report_root = Path(os.getenv("KB_REPORT_STAGING_ROOT", "/app/data/report-staging"))
    upload_root = Path(os.getenv("KB_INGEST_UPLOAD_ROOT", "/app/data/uploads"))
    for item in items:
        target = _safe_path(report_root, item.get("original_path"))
        if target:
            targets.append(target)
        for attachment in item.get("attachments", []):
            target = _safe_path(report_root, attachment.get("path"))
            if target:
                targets.append(target)
    for item in ingest_items:
        for key in ("original_path", "converted_path"):
            target = _safe_path(upload_root, item.get(key))
            if target:
                targets.append(target)
    unique: list[Path] = []
    seen: set[str] = set()
    for target in targets:
        key = str(target.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(target)
    return unique


def _neo4j_counts(run_id: str, environment: str | None = None) -> dict[str, int]:
    from neo4j import GraphDatabase
    from ..main import load_config
    config = load_config().get("neo4j", {})
    driver = GraphDatabase.driver(
        config.get("uri", "bolt://neo4j:7687"),
        auth=(config.get("user", "neo4j"), config.get("password") or os.getenv("NEO4J_PASSWORD", "")),
    )
    counts: dict[str, int] = {}
    try:
        with driver.session() as session:
            for label in ("TestRun", "TestCase", "Measurement"):
                where = "n.run_id = $run_id" + (" AND n.environment = $environment" if environment else "")
                record = session.run(f"MATCH (n:{label}) WHERE {where} RETURN count(n) AS count", run_id=run_id, environment=environment).single()
                counts[label] = int(record["count"] if record else 0)
    finally:
        driver.close()
    return counts


def _neo4j_delete(run_id: str, environment: str | None = None) -> dict[str, int]:
    from neo4j import GraphDatabase
    from ..main import load_config
    config = load_config().get("neo4j", {})
    driver = GraphDatabase.driver(
        config.get("uri", "bolt://neo4j:7687"),
        auth=(config.get("user", "neo4j"), config.get("password") or os.getenv("NEO4J_PASSWORD", "")),
    )
    counts: dict[str, int] = {}
    try:
        with driver.session() as session:
            for label in ("Measurement", "TestCase", "TestRun"):
                where = "n.run_id = $run_id" + (" AND n.environment = $environment" if environment else "")
                record = session.run(f"MATCH (n:{label}) WHERE {where} DETACH DELETE n RETURN count(n) AS count", run_id=run_id, environment=environment).single()
                counts[label] = int(record["count"] if record else 0)
    finally:
        driver.close()
    return counts


def _qdrant_client():
    from qdrant_client import QdrantClient
    from ..runtime_config import resolve_qdrant_url
    from ..main import load_config

    config = load_config()
    configured_url = (config.get("qdrant") or {}).get("url")
    candidate = os.getenv("QDRANT_URL") or configured_url or "http://host.docker.internal:6333"
    return QdrantClient(url=resolve_qdrant_url(candidate), timeout=30)


def _qdrant_filter(run_id: str, environment: str | None):
    from qdrant_client.models import FieldCondition, Filter, MatchValue
    must = [FieldCondition(key="run_id", match=MatchValue(value=run_id))]
    if environment:
        must.append(FieldCondition(key="environment", match=MatchValue(value=environment)))
    return Filter(must=must)


def _qdrant_count(run_id: str, environment: str | None) -> int:
    client = _qdrant_client()
    if hasattr(client, "collection_exists") and not client.collection_exists(collection_name="knowledge_base"):
        return 0
    result = client.count(collection_name="knowledge_base", count_filter=_qdrant_filter(run_id, environment), exact=True)
    return int(result.count)


def _qdrant_delete(run_id: str, environment: str | None) -> int:
    client = _qdrant_client()
    if hasattr(client, "collection_exists") and not client.collection_exists(collection_name="knowledge_base"):
        return 0
    count = _qdrant_count(run_id, environment)
    client.delete(collection_name="knowledge_base", points_selector=_qdrant_filter(run_id, environment), wait=True)
    return count


def build_cleanup_plan(test_run_id: str, environment: str | None = None) -> dict[str, Any]:
    if not _allowed_test_run_id(test_run_id):
        raise ValueError("test_run_id 不符合已設定的 E2E cleanup prefix")
    reports = _report_items(test_run_id)
    ingests = _ingest_items(test_run_id)
    task_ids = {item.get("ingest_task_id") for item in reports if item.get("ingest_task_id")}
    task_ids.update(item.get("task_id") for item in ingests if item.get("task_id"))
    tasks = {task_id: _task_state(task_id) for task_id in task_ids}
    active = [state for state in tasks.values() if state and state.get("status") in ACTIVE_STATUSES]
    return {
        "test_run_id": test_run_id,
        "environment": environment,
        "reports": [{"submission_id": item.get("submission_id"), "status": item.get("status"), "environment": item.get("environment")} for item in reports],
        "ingest_records": [{"task_id": item.get("task_id"), "status": item.get("status"), "environment_id": item.get("environment_id")} for item in ingests],
        "task_ids": sorted(task_ids),
        "active_task_count": len(active),
        "file_target_count": len(_file_targets(reports, ingests)),
        "neo4j": _neo4j_counts(test_run_id, environment),
        "qdrant": {"points": _qdrant_count(test_run_id, environment)},
    }


def apply_cleanup(test_run_id: str, environment: str | None = None) -> dict[str, Any]:
    plan = build_cleanup_plan(test_run_id, environment)
    if plan["active_task_count"]:
        raise RuntimeError("拒絕清理：仍有 active ingest task")
    reports = _report_items(test_run_id)
    ingests = _ingest_items(test_run_id)
    file_targets = _file_targets(reports, ingests)
    deleted_files = 0
    for target in file_targets:
        if target.is_file():
            target.unlink()
            deleted_files += 1
    deleted_tasks = 0
    for task_id in plan["task_ids"]:
        _delete_task_state(task_id, _task_state(task_id))
        deleted_tasks += 1
    deleted_qdrant = _qdrant_delete(test_run_id, environment)
    deleted_neo4j = _neo4j_delete(test_run_id, environment)
    deleted_reports = sum(
        SubmissionRegistry().delete_by_submission_id(item["submission_id"], test_run_id)
        for item in reports if item.get("status") in {"pending_review", "rejected", "completed", "ingest_failed", "queued"}
    )
    deleted_ingests = IngestRegistry().delete_by_run(test_run_id)
    return {
        "test_run_id": test_run_id,
        "environment": environment,
        "deleted": {
            "files": deleted_files,
            "redis_tasks": deleted_tasks,
            "reports": deleted_reports,
            "ingest_records": deleted_ingests,
            "neo4j": deleted_neo4j,
            "qdrant_points": deleted_qdrant,
        },
    }
