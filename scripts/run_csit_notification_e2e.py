#!/usr/bin/env python3
"""Run a disposable, KM-only CSIT-notification-to-search validation.

The sender and XLSX artifact are synthetic.  After receipt, execution uses the
real KM API, Celery workers, report parser, registry, Neo4j, Qdrant,
TimescaleDB, report APIs and search task.  It never reads CSIT settings or
normal KM compose files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import requests
from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.csit-e2e.yml"
RUN_PREFIX = "KM-CSIT-E2E-"


def _run(args: list[str], *, env: dict[str, str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, env=env, check=True, text=True, capture_output=capture)


def _port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _write_fixture(path: Path, run_id: str) -> str:
    workbook = Workbook()
    manifest = workbook.active
    manifest.title = "Manifest"
    manifest.append(["key", "value"])
    for key, value in {
        "schema_version": "1.0", "run_id": run_id, "environment": "anritsu",
        "project_code": "SCU2060", "dut_model": "KM-E2E-DUT",
        "started_at": "2026-09-24T08:00:00+08:00", "finished_at": "2026-09-24T08:10:00+08:00",
        "overall_verdict": "Pass", "revision": "e2e-v1",
    }.items():
        manifest.append([key, value])
    sheets = {
        "RadioConfig": (["key", "value", "unit"], [["band", "n78", ""]]),
        "TestCases": (["case_id", "name", "status"], [["TC-E2E-01", "SCU2060 CSIT notification throughput", "completed"]]),
        "Measurements": (
            ["case_id", "metric", "value", "unit", "lower_limit", "upper_limit", "observed_at"],
            [["TC-E2E-01", "throughput", 910.0, "Mbps", 900, None, "2026-09-24T08:01:00+08:00"],
             ["TC-E2E-01", "throughput", 920.0, "Mbps", 900, None, "2026-09-24T08:02:00+08:00"],
             ["TC-E2E-01", "throughput", 930.0, "Mbps", 900, None, "2026-09-24T08:03:00+08:00"]],
        ),
        "Verdicts": (["case_id", "verdict", "reason"], [["TC-E2E-01", "Pass", "synthetic fixture"]]),
        "RawArtifacts": (["artifact_path", "sha256"], []),
    }
    for name, (headers, rows) in sheets.items():
        sheet = workbook.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    workbook.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait_json(url: str, headers: dict[str, str], *, timeout: int = 180) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        last = response.json()
        if last.get("status") in {"completed", "failed", "partial_failed", "held"}:
            return last
        time.sleep(2)
    raise RuntimeError(f"timeout waiting for terminal state: {last}")


def _compose(project: str, env: dict[str, str], *args: str, capture: bool = False) -> subprocess.CompletedProcess:
    return _run(["docker", "compose", "-p", project, "-f", str(COMPOSE), *args], env=env, capture=capture)


def _container_python(project: str, env: dict[str, str], code: str) -> str:
    result = _compose(
        project, env, "exec", "-T",
        "-e", f"KM_CSIT_E2E_RUN_ID={env['KM_CSIT_E2E_RUN_ID']}",
        "-e", f"KM_CSIT_E2E_DOCUMENT_ID={env['KM_CSIT_E2E_DOCUMENT_ID']}",
        "web", "python", "-c", code, capture=True,
    )
    return result.stdout.strip()


def _cleanup_data(project: str, env: dict[str, str], run_id: str) -> dict[str, int]:
    code = """
import json, os
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
from src.timeseries_store import TimeseriesStore
run_id = os.environ['KM_CSIT_E2E_RUN_ID']
document_id = os.environ['KM_CSIT_E2E_DOCUMENT_ID']
q = QdrantClient(url=os.environ['QDRANT_URL'])
f = Filter(should=[FieldCondition(key='run_id', match=MatchValue(value=run_id)), FieldCondition(key='document_id', match=MatchValue(value=document_id))])
points = q.count('knowledge_base', count_filter=f, exact=True).count if q.collection_exists('knowledge_base') else 0
if points: q.delete('knowledge_base', points_selector=f, wait=True)
d = GraphDatabase.driver(os.environ['NEO4J_URI'], auth=(os.environ['NEO4J_USER'], os.environ['NEO4J_PASSWORD']))
with d.session() as s:
    neo = s.run('MATCH (n) WHERE n.run_id=$run_id OR n.document_id=$document_id DETACH DELETE n RETURN count(n) AS c', run_id=run_id, document_id=document_id).single()['c']
    neo_remaining = s.run('MATCH (n) WHERE n.run_id=$run_id OR n.document_id=$document_id RETURN count(n) AS c', run_id=run_id, document_id=document_id).single()['c']
d.close()
t = TimeseriesStore()
with t._connect() as c:
    c.execute('DELETE FROM metric_sample WHERE run_id=%s', (run_id,))
    c.execute('DELETE FROM test_run_summary WHERE run_id=%s', (run_id,))
    c.execute('DELETE FROM test_run WHERE run_id=%s', (run_id,))
with t._connect() as c:
    ts = sum(c.execute('SELECT count(*) AS c FROM ' + table + ' WHERE run_id=%s', (run_id,)).fetchone()['c'] for table in ('test_run','metric_sample','test_run_summary'))
remaining = q.count('knowledge_base', count_filter=f, exact=True).count if q.collection_exists('knowledge_base') else 0
print(json.dumps({'qdrant_deleted': points, 'neo4j_deleted': neo, 'timescale_residual': ts, 'qdrant_residual': remaining, 'neo4j_residual': neo_remaining}))
"""
    return json.loads(_container_python(project, env, code))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="keep the disposable compose project and evidence root")
    parser.add_argument("--output-dir", type=Path, help="copy sanitized evidence here")
    args = parser.parse_args()
    if not COMPOSE.is_file():
        raise SystemExit("docker-compose.csit-e2e.yml is missing")

    run_id = RUN_PREFIX + uuid.uuid4().hex[:12]
    project = "kmcsit" + uuid.uuid4().hex[:8]
    port = _port()
    sender_token = "km-e2e-sender-" + uuid.uuid4().hex
    reviewer_token = "km-e2e-reviewer-" + uuid.uuid4().hex
    document_id = "csit-doc-" + run_id
    evidence_root = Path(tempfile.mkdtemp(prefix="km-csit-e2e-"))
    docker_config = evidence_root / "docker-config"
    docker_config.mkdir(mode=0o700)
    fixture = evidence_root / "fixture.xlsx"
    digest = _write_fixture(fixture, run_id)
    reviewer_hash = hashlib.sha256(reviewer_token.encode()).hexdigest()
    env = {**os.environ,
           "KM_CSIT_E2E_ROOT": str(evidence_root), "KM_CSIT_E2E_PORT": str(port),
           "KM_CSIT_E2E_SENDER_TOKEN": sender_token,
           "KM_CSIT_E2E_REVIEWER_HASH": json.dumps({"e2e-reviewer": reviewer_hash}),
           "KM_CSIT_NOTIFICATION_FIXTURES_JSON": json.dumps({"approved": {"path": "/e2e/fixture.xlsx", "sha256": digest}}),
           "KM_CSIT_E2E_RUN_ID": run_id, "KM_CSIT_E2E_DOCUMENT_ID": document_id,
           # Keep Buildx activity/cache metadata outside the user's Docker
           # configuration.  Public images and the local daemon are enough.
           "DOCKER_CONFIG": str(docker_config)}
    evidence: dict[str, Any] = {"run_id": run_id, "project": project, "csit": "simulated", "production": "not_touched"}
    base = f"http://127.0.0.1:{port}"
    try:
        _compose(project, env, "config", "--quiet")
        _compose(project, env, "up", "--build", "-d", "--wait")
        _compose(project, env, "exec", "-T", "web", "python", "scripts/apply_timeseries_migrations.py")
        payload = {"schema_version": "1.0-draft", "event_id": "evt-" + run_id,
                   "event_type": "csit.test.document.available", "document_id": document_id,
                   "document_version": "e2e-v1", "file_ref": {"fixture_id": "approved"},
                   "occurred_at": "2026-09-24T00:00:00Z", "correlation_id": "corr-" + run_id}
        headers = {"Authorization": "Bearer " + sender_token}
        accepted = requests.post(base + "/api/v1/integrations/csit/events", json=payload, headers=headers, timeout=20)
        if accepted.status_code != 202:
            raise RuntimeError(f"notification was not accepted: HTTP {accepted.status_code}")
        duplicate = requests.post(base + "/api/v1/integrations/csit/events", json=payload, headers=headers, timeout=20)
        conflict_payload = {**payload, "document_version": "e2e-conflict"}
        conflict = requests.post(base + "/api/v1/integrations/csit/events", json=conflict_payload, headers=headers, timeout=20)
        if duplicate.status_code != 202 or not duplicate.json().get("duplicate") or conflict.status_code != 409:
            raise RuntimeError("idempotency/conflict contract failed")
        terminal = _wait_json(base + accepted.json()["status_url"], headers)
        if terminal.get("status") != "completed":
            raise RuntimeError("existing KM ingest did not complete: " + str(terminal))
        report_headers = {"Authorization": "Bearer " + reviewer_token, "X-KM-Project": "SCU2060", "X-KM-Role": "report-reader"}
        summary = requests.get(base + f"/api/v1/reports/{run_id}/timeseries/summary?version=e2e-v1", headers=report_headers, timeout=20)
        if summary.status_code != 200 or len(summary.json().get("items", [])) != 1:
            raise RuntimeError("Timescale summary/provenance check failed")
        search = requests.post(base + "/search", json={"query": "SCU2060 CSIT notification throughput", "mode": "vector", "top_k": 5, "sources_only": True, "filters": {"run_id": run_id}}, timeout=20)
        search.raise_for_status()
        task_id = search.json()["task_id"]
        task = _wait_json(base + "/tasks/" + task_id, {}, timeout=120)
        sources = task.get("sources") or []
        if not any(item.get("run_id") == run_id and item.get("source_file_hash") == digest for item in sources):
            observed = [{key: item.get(key, "") for key in ("run_id", "document_id", "source_file_hash")}
                        for item in sources[:5]]
            raise RuntimeError("Search provenance check failed: " + json.dumps(observed, sort_keys=True))
        evidence.update({"notification": {"accepted": True, "duplicate": True, "conflict": True, "terminal": terminal},
                         "timeseries": {"summary_items": len(summary.json()["items"])},
                         "search": {"source_count": len(sources), "provenance": True}})
        evidence["cleanup"] = _cleanup_data(project, env, run_id)
        if any(value != 0 for key, value in evidence["cleanup"].items() if key.endswith("residual")):
            raise RuntimeError("cleanup residual is non-zero")
        evidence["status"] = "PASS"
    except Exception as exc:
        evidence.update({"status": "FAIL", "error": type(exc).__name__, "message": str(exc)[:500]})
        raise
    finally:
        (evidence_root / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(evidence_root / "evidence.json", args.output_dir / "csit-notification-e2e-evidence.json")
        if not args.keep:
            subprocess.run(["docker", "compose", "-p", project, "-f", str(COMPOSE), "down", "-v", "--remove-orphans"], cwd=ROOT, env=env, check=False)
            shutil.rmtree(evidence_root, ignore_errors=True)
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
