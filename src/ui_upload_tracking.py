"""Per-instance Timescale tracking for browser uploads; file contents stay out of this store."""
from __future__ import annotations

import os
from datetime import datetime, timezone


def _connect():
    import psycopg
    url = os.getenv("TIMESCALEDB_URL")
    if not url:
        raise RuntimeError("TIMESCALEDB_URL is not configured")
    return psycopg.connect(url)


def record_upload(*, task_id: str, data_zone: str, file_name: str, file_hash: str,
                  extraction_mode: str, status: str, report: dict | None = None) -> None:
    """Upsert one upload and, for validated reports, their structured measurements."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS km_ui_uploads (
                    task_id text PRIMARY KEY, data_zone text NOT NULL,
                    file_name text NOT NULL, file_hash char(64) NOT NULL,
                    extraction_mode text NOT NULL, status text NOT NULL,
                    run_id text, uploaded_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS km_ui_report_measurements (
                    data_zone text NOT NULL, run_id text NOT NULL, case_id text NOT NULL,
                    metric text NOT NULL, sample_index integer NOT NULL,
                    value double precision NOT NULL, unit text NOT NULL,
                    started_at timestamptz NOT NULL, task_id text NOT NULL,
                    recorded_at timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (data_zone, run_id, case_id, metric, sample_index)
                )
            """)
            manifest = (report or {}).get("manifest", {})
            cur.execute("""
                INSERT INTO km_ui_uploads(task_id,data_zone,file_name,file_hash,extraction_mode,status,run_id,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT(task_id) DO UPDATE SET status=excluded.status, updated_at=now(), run_id=coalesce(excluded.run_id,km_ui_uploads.run_id)
            """, (task_id, data_zone, file_name, file_hash, extraction_mode, status, manifest.get("run_id")))
            if report:
                started = datetime.fromisoformat(manifest["started_at"].replace("Z", "+00:00"))
                cur.executemany("""
                    INSERT INTO km_ui_report_measurements(data_zone,run_id,case_id,metric,sample_index,value,unit,started_at,task_id)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(data_zone,run_id,case_id,metric,sample_index) DO UPDATE SET value=excluded.value,unit=excluded.unit,started_at=excluded.started_at,task_id=excluded.task_id,recorded_at=now()
                """, [(data_zone, manifest["run_id"], str(row["case_id"]), str(row["metric"]), index, float(row["value"]), str(row.get("unit") or ""), started, task_id) for index, row in enumerate(report.get("measurements", []))])


def update_upload_status(state: dict, status: str) -> None:
    if not state.get("ui_session_upload"):
        return
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE km_ui_uploads SET status=%s,updated_at=now() WHERE task_id=%s", (status, state["task_id"]))
