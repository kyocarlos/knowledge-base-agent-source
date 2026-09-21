"""TimescaleDB storage adapter for structured KM test-report measurements.

The adapter owns only technical persistence and queries.  It does not decide
business publication and does not create a second parser or ingest workflow.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MIGRATION_DIR = Path(__file__).resolve().parents[1] / "migrations" / "timeseries"


class TimeseriesValidationError(ValueError):
    pass


def _iso(value: Any, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise TimeseriesValidationError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise TimeseriesValidationError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise TimeseriesValidationError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value if isinstance(value, dict) else {}, ensure_ascii=False, sort_keys=True)


def _sample_key(run_id: str, version: str, row: dict[str, Any], observed: datetime, sequence: str) -> str:
    material = "\x1f".join((run_id, version, str(row.get("case_id") or ""),
                             str(row.get("metric") or ""), observed.isoformat(), sequence,
                             str(row.get("value")), str(row.get("unit") or "")))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class TimeseriesStore:
    def __init__(self, database_url: str | None = None):
        self.database_url = database_url or os.getenv("KM_TIMESERIES_DATABASE_URL", "")
        if not self.database_url:
            raise RuntimeError("KM_TIMESERIES_DATABASE_URL is not configured")

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def apply_migrations(self, migration_dir: str | Path = MIGRATION_DIR) -> list[str]:
        """Apply ordered SQL once; this is an operator/CI action, never an API side effect."""
        applied: list[str] = []
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS km_schema_migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())")
            for path in sorted(Path(migration_dir).glob("*.sql")):
                version = path.name
                if conn.execute("SELECT 1 FROM km_schema_migrations WHERE version=%s", (version,)).fetchone():
                    continue
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO km_schema_migrations(version) VALUES (%s)", (version,))
                applied.append(version)
        return applied

    def ingest_report(self, report: dict[str, Any], *, document_id: str, document_version: str,
                      source_file_name: str, source_file_sha256: str, publish_status: str = "published",
                      is_current: bool = True, acl: dict[str, Any] | None = None,
                      package_id: str | None = None, source_locator: dict[str, Any] | None = None) -> dict[str, Any]:
        manifest = report["manifest"]
        run_id = str(manifest["run_id"])
        started = _iso(manifest["started_at"], "started_at")
        finished = _iso(manifest["finished_at"], "finished_at")
        if finished < started:
            raise TimeseriesValidationError("finished_at must not precede started_at")
        samples: list[tuple[Any, ...]] = []
        summaries: dict[tuple[str, str, str], list[float]] = {}
        for index, row in enumerate(report.get("measurements", [])):
            raw_value = row.get("value")
            try:
                value = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise TimeseriesValidationError(f"measurement[{index}].value must be numeric") from exc
            if not (value == value and abs(value) != float("inf")):
                raise TimeseriesValidationError(f"measurement[{index}].value must be finite")
            unit = str(row.get("unit") or "").strip()
            metric = str(row.get("metric") or "").strip()
            case_id = str(row.get("case_id") or "").strip()
            if not metric or not unit or not case_id:
                raise TimeseriesValidationError(f"measurement[{index}] requires case_id, metric and unit")
            observed_raw = row.get("observed_at") or row.get("timestamp") or row.get("time")
            # A summary-only row is not invented as a time-series point.
            if not observed_raw:
                continue
            observed = _iso(observed_raw, f"measurement[{index}].observed_at")
            sequence = str(row.get("sequence_key") or row.get("sequence") or "").strip()
            dimensions = row.get("dimensions") if isinstance(row.get("dimensions"), dict) else {}
            locator = {"sheet": "Measurements", "row": index + 2}
            key = _sample_key(run_id, document_version, row, observed, sequence)
            samples.append((observed, key, run_id, document_version, case_id, metric, value, unit,
                            str(raw_value), unit, sequence, _json(dimensions), _json(locator)))
            summaries.setdefault((case_id, metric, unit), []).append(value)

        with self._connect() as conn:
            conn.execute("""INSERT INTO test_run
                (run_id,document_id,document_version,revision,package_id,report_id,source_file_name,
                 source_file_sha256,project_code,dut_model,firmware,test_case,band,direction,started_at,
                 finished_at,overall_verdict,publish_status,is_current,acl,source_locator,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                ON CONFLICT (run_id, document_version) DO UPDATE SET
                 source_file_sha256=EXCLUDED.source_file_sha256, publish_status=EXCLUDED.publish_status,
                 is_current=EXCLUDED.is_current, acl=EXCLUDED.acl, source_locator=EXCLUDED.source_locator,
                 updated_at=now()""",
                (run_id, document_id, document_version, str(manifest.get("revision") or "1"), package_id,
                 manifest.get("report_id"), source_file_name, source_file_sha256, manifest["project_code"],
                 manifest["dut_model"], manifest.get("firmware"), manifest.get("test_case"), manifest.get("band"),
                 manifest.get("direction"), started, finished, manifest["overall_verdict"], publish_status,
                 is_current, _json(acl), _json(source_locator or {"source": source_file_name})))
            conn.execute("DELETE FROM metric_sample WHERE run_id=%s AND document_version=%s", (run_id, document_version))
            for item in samples:
                conn.execute("""INSERT INTO metric_sample
                    (observed_at,sample_key,run_id,document_version,case_id,metric_name,value,unit,raw_value,
                     raw_unit,sequence_key,dimensions,source_locator)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (observed_at,sample_key) DO NOTHING""", item)
            conn.execute("DELETE FROM test_run_summary WHERE run_id=%s AND document_version=%s", (run_id, document_version))
            for (case_id, metric, unit), values in summaries.items():
                conn.execute("""INSERT INTO test_run_summary
                    (run_id,document_version,case_id,metric_name,unit,min_value,max_value,avg_value,sample_count,source_locator)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (run_id, document_version, case_id, metric, unit, min(values), max(values),
                     sum(values) / len(values), len(values), _json({"sheet": "Measurements"})))
        return {"run_id": run_id, "document_version": document_version, "sample_count": len(samples),
                "summary_count": len(summaries), "persisted": True}

    def list_runs(self, project_code: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("""SELECT run_id,document_id,document_version,project_code,dut_model,
                started_at,finished_at,overall_verdict,publish_status,is_current,source_file_name,source_file_sha256
                FROM test_run WHERE project_code=%s AND publish_status='published' AND is_current=true
                ORDER BY started_at DESC LIMIT %s""", (project_code, max(1, min(limit, 100)))).fetchall()
        return [dict(row) for row in rows]

    def get_run(self, run_id: str, project_code: str, version: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("""SELECT * FROM test_run WHERE run_id=%s AND project_code=%s
                AND publish_status='published' AND is_current=true
                AND (%s::text IS NULL OR document_version=%s) ORDER BY document_version DESC LIMIT 1""",
                (run_id, project_code, version, version)).fetchone()
        return dict(row) if row else None

    def get_summary(self, run_id: str, version: str, project_code: str) -> list[dict[str, Any]]:
        if not self.get_run(run_id, project_code, version):
            return []
        with self._connect() as conn:
            rows = conn.execute("""SELECT case_id,metric_name,unit,min_value,max_value,avg_value,sample_count,source_locator
                FROM test_run_summary WHERE run_id=%s AND document_version=%s ORDER BY case_id,metric_name""", (run_id, version)).fetchall()
        return [dict(row) for row in rows]

    def get_samples(self, run_id: str, version: str, project_code: str, metric: str | None = None,
                    start: str | None = None, end: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
        if not self.get_run(run_id, project_code, version):
            return []
        conditions = ["run_id=%s", "document_version=%s"]
        params: list[Any] = [run_id, version]
        if metric:
            conditions.append("metric_name=%s"); params.append(metric)
        if start:
            conditions.append("observed_at >= %s"); params.append(_iso(start, "start"))
        if end:
            conditions.append("observed_at < %s"); params.append(_iso(end, "end"))
        params.append(max(1, min(limit, 5000)))
        with self._connect() as conn:
            rows = conn.execute(f"""SELECT observed_at,case_id,metric_name,value,unit,sequence_key,dimensions,source_locator
                FROM metric_sample WHERE {' AND '.join(conditions)} ORDER BY observed_at ASC LIMIT %s""", tuple(params)).fetchall()
        return [dict(row) for row in rows]
