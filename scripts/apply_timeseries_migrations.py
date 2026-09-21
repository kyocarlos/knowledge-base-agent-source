"""Apply KM-TS-REPORT migrations using the explicitly supplied DB URL."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.timeseries_store import TimeseriesStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()
    try:
        applied = TimeseriesStore(args.database_url or os.getenv("KM_TIMESERIES_DATABASE_URL")).apply_migrations()
    except Exception as exc:
        print(f"TIMESERIES_MIGRATION_FAIL {type(exc).__name__}", file=sys.stderr)
        return 1
    print("TIMESERIES_MIGRATION_PASS applied=" + (",".join(applied) if applied else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
