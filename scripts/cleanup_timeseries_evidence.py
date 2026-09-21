"""Delete only the disposable KM-TS-CI run and print actual residual counts."""
from __future__ import annotations

import os
import psycopg


def main() -> int:
    url = os.getenv("KM_TIMESERIES_DATABASE_URL")
    if not url:
        raise SystemExit("KM_TIMESERIES_DATABASE_URL is required")
    with psycopg.connect(url) as conn:
        conn.execute("DELETE FROM metric_sample WHERE run_id='KM-TS-CI-001'")
        conn.execute("DELETE FROM test_run_summary WHERE run_id='KM-TS-CI-001'")
        conn.execute("DELETE FROM test_run WHERE run_id='KM-TS-CI-001'")
        counts = {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                  for table in ("test_run", "metric_sample", "test_run_summary")}
    print(f"TIMESERIES_CLEANUP_PASS residual={counts}")
    if any(counts.values()):
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
