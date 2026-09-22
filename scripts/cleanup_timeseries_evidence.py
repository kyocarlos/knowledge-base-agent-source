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
        counts = {
            "test_run": conn.execute("SELECT count(*) FROM test_run WHERE run_id='KM-TS-CI-001'").fetchone()[0],
            "metric_sample": conn.execute("SELECT count(*) FROM metric_sample WHERE run_id='KM-TS-CI-001'").fetchone()[0],
            "test_run_summary": conn.execute("SELECT count(*) FROM test_run_summary WHERE run_id='KM-TS-CI-001'").fetchone()[0],
        }
    print(f"TIMESERIES_CLEANUP_PASS residual_for_run={counts}")
    if any(counts.values()):
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
