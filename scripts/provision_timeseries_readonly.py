"""Provision the pgAdmin read-only login using deployment secrets only."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.timeseries_store import TimeseriesStore


def main() -> int:
    migration_url = os.getenv("KM_TIMESERIES_MIGRATION_URL", "")
    password = os.getenv("KM_TIMESERIES_READONLY_PASSWORD", "")
    if not migration_url or not password:
        print("TIMESERIES_READONLY_PROVISION_FAIL required deployment secrets are unset", file=sys.stderr)
        return 2
    try:
        with TimeseriesStore(migration_url)._connect() as conn:
            conn.execute("ALTER ROLE km_ts_readonly LOGIN PASSWORD %s", (password,))
            conn.execute("GRANT USAGE ON SCHEMA public TO km_ts_readonly")
            conn.execute("GRANT SELECT ON test_run, metric_sample, test_run_summary TO km_ts_readonly")
    except Exception as exc:
        print(f"TIMESERIES_READONLY_PROVISION_FAIL {type(exc).__name__}", file=sys.stderr)
        return 1
    print("TIMESERIES_READONLY_PROVISION_PASS role=km_ts_readonly grants=select")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
