"""End-to-end isolated KM-TS-REPORT evidence, including DB and readonly role."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from openpyxl import Workbook

from src.test_reports.excel_contract import parse_and_validate_report
from src.timeseries_store import TimeseriesStore

DB_URL = os.getenv("KM_TIMESERIES_DATABASE_URL", "postgresql://km_ci:ci-timescale-password@127.0.0.1:15433/km_ci")
READONLY_URL = os.getenv("KM_TIMESERIES_READONLY_URL", "postgresql://km_ts_readonly:ci-timeseries-readonly@127.0.0.1:15433/km_ci")


def make_fixture(path: Path) -> str:
    wb = Workbook()
    manifest = wb.active
    manifest.title = "Manifest"
    manifest.append(["key", "value"])
    values = {
        "schema_version": "1.0", "run_id": "KM-TS-CI-001", "environment": "anritsu",
        "project_code": "KM-CI", "dut_model": "DUT-CI", "started_at": "2026-09-21T01:00:00+00:00",
        "finished_at": "2026-09-21T01:05:00+00:00", "overall_verdict": "pass", "revision": "r1",
    }
    for key, value in values.items(): manifest.append([key, value])
    for name, headers, rows in [
        ("RadioConfig", ["key", "value", "unit"], [["band", "n78", ""]]),
        ("TestCases", ["case_id", "name", "status"], [["TC-1", "Throughput", "pass"]]),
        ("Measurements", ["case_id", "metric", "value", "unit", "observed_at", "sequence_key"], [
            ["TC-1", "throughput", 10, "Mbps", "2026-09-21T01:01:00+00:00", "ue-1"],
            ["TC-1", "throughput", 20, "Mbps", "2026-09-21T01:02:00+00:00", "ue-1"],
            ["TC-1", "throughput", 30, "Mbps", "2026-09-21T01:03:00+00:00", "ue-1"],
        ]),
        ("Verdicts", ["case_id", "verdict", "reason"], [["TC-1", "pass", "within target"]]),
        ("RawArtifacts", ["artifact_path", "sha256"], []),
    ]:
        sheet = wb.create_sheet(name)
        sheet.append(headers)
        for row in rows: sheet.append(row)
    wb.save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wait_for_db() -> None:
    deadline = time.monotonic() + 60
    while True:
        try:
            with psycopg.connect(DB_URL) as conn:
                conn.execute("SELECT 1").fetchone()
            return
        except Exception:
            if time.monotonic() >= deadline: raise
            time.sleep(2)


def main() -> int:
    wait_for_db()
    store = TimeseriesStore(DB_URL)
    applied = store.apply_migrations()
    rerun = store.apply_migrations()
    if rerun:
        raise RuntimeError(f"migration rerun was not idempotent: {rerun}")
    with tempfile.TemporaryDirectory(prefix="km-ts-fixture-") as folder:
        fixture = Path(folder) / "KM_TS_CI.xlsx"
        digest = make_fixture(fixture)
        parsed = parse_and_validate_report(fixture, {})
        first = store.ingest_report(parsed, document_id="doc:KM-TS-CI-001", document_version="r1",
                                    source_file_name=fixture.name, source_file_sha256=digest,
                                    publish_status="published", is_current=True,
                                    acl={"project_code": "KM-CI"})
        repeat = store.ingest_report(parsed, document_id="doc:KM-TS-CI-001", document_version="r1",
                                     source_file_name=fixture.name, source_file_sha256=digest,
                                     publish_status="published", is_current=True,
                                     acl={"project_code": "KM-CI"})
    if first["sample_count"] != 3 or repeat["sample_count"] != 3:
        raise RuntimeError("sample persistence/idempotency expectation failed")
    summary = store.get_summary("KM-TS-CI-001", "r1", "KM-CI")
    samples = store.get_samples("KM-TS-CI-001", "r1", "KM-CI", metric="throughput", limit=10)
    if len(summary) != 1 or summary[0]["avg_value"] != 20 or len(samples) != 3:
        raise RuntimeError("summary or query golden expectation failed")
    with psycopg.connect(DB_URL) as conn:
        hypertable = conn.execute("SELECT hypertable_name FROM timescaledb_information.hypertables WHERE hypertable_name='metric_sample'").fetchone()
        conn.execute("""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='km_ts_readonly') THEN
                CREATE ROLE km_ts_readonly LOGIN PASSWORD 'ci-timescale-readonly';
            ELSE
                ALTER ROLE km_ts_readonly LOGIN PASSWORD 'ci-timescale-readonly';
            END IF;
        END $$""")
        conn.execute("GRANT USAGE ON SCHEMA public TO km_ts_readonly")
        conn.execute("GRANT SELECT ON test_run, metric_sample, test_run_summary TO km_ts_readonly")
    if not hypertable:
        raise RuntimeError("metric_sample is not a Timescale hypertable")
    with psycopg.connect(READONLY_URL) as conn:
        if conn.execute("SELECT count(*) FROM metric_sample").fetchone()[0] != 3:
            raise RuntimeError("readonly query did not see persisted samples")
        try:
            conn.execute("INSERT INTO test_run(run_id,document_id,document_version,source_file_name,source_file_sha256,project_code,dut_model,started_at,finished_at,overall_verdict) VALUES ('nope','nope','nope','nope','nope','nope','nope',now(),now(),'pass')")
        except psycopg.errors.InsufficientPrivilege:
            conn.rollback()
        else:
            raise RuntimeError("readonly role could write")
    print(json.dumps({"status": "PASS", "migration_applied": applied, "migration_rerun_safe": True, "hypertable": "metric_sample",
                      "rows": {"samples": len(samples), "summary": len(summary)},
                      "idempotent_repeat": True, "readonly": {"select": True, "insert_denied": True}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
