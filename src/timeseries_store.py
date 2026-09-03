"""Independent time-series metric storage for KM014."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any


class TimeSeriesStore:
    """Store numeric test metrics separately from the report registry."""

    def __init__(self, database_url: str | None = None):
        self.database_url = (database_url or os.getenv("TIMESCALEDB_URL", "")).strip()
        if not self.database_url:
            raise RuntimeError("TIMESCALEDB_URL is required")

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("TimescaleDB client unavailable") from exc
        return psycopg.connect(self.database_url)

    def ensure_schema(self) -> None:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS km_timeseries_metrics (
                        test_run_id TEXT NOT NULL,
                        observed_at TIMESTAMPTZ NOT NULL,
                        metric_name TEXT NOT NULL,
                        value DOUBLE PRECISION NOT NULL,
                        unit TEXT NOT NULL,
                        package_id TEXT,
                        document_id TEXT,
                        PRIMARY KEY (test_run_id, observed_at, metric_name)
                    )
                    """
                )

    def write_metric(self, metric: dict[str, Any]) -> dict[str, Any]:
        self.ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO km_timeseries_metrics
                        (test_run_id, observed_at, metric_name, value, unit, package_id, document_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (test_run_id, observed_at, metric_name) DO UPDATE SET
                        value = EXCLUDED.value,
                        unit = EXCLUDED.unit,
                        package_id = EXCLUDED.package_id,
                        document_id = EXCLUDED.document_id
                    """ ,
                    (
                        metric["test_run_id"], metric["observed_at"], metric["metric_name"],
                        metric["value"], metric["unit"], metric.get("package_id"), metric.get("document_id"),
                    ),
                )
        return {key: metric.get(key) for key in ("test_run_id", "observed_at", "metric_name", "value", "unit", "package_id", "document_id")}

    def query_metrics(self, test_run_id: str, start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
        self.ensure_schema()
        clauses = ["test_run_id = %s"]
        values: list[Any] = [test_run_id]
        if start is not None:
            clauses.append("observed_at >= %s")
            values.append(start)
        if end is not None:
            clauses.append("observed_at <= %s")
            values.append(end)
        query = "SELECT test_run_id, observed_at, metric_name, value, unit, package_id, document_id FROM km_timeseries_metrics WHERE " + " AND ".join(clauses) + " ORDER BY observed_at, metric_name"
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(query, values)
                columns = [item.name for item in cursor.description]
                return [dict(zip(columns, row)) for row in cursor.fetchall()]
