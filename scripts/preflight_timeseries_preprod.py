"""Read-only readiness gate for the isolated KM TimescaleDB pre-production run."""
from __future__ import annotations

import os
import shutil
import socket
from pathlib import Path


REQUIRED = (
    "KB_TIMESERIES_DB_PASSWORD", "KM_PGADMIN_EMAIL", "KM_PGADMIN_PASSWORD",
    "KM_TIMESERIES_MIGRATION_URL", "KM_TIMESERIES_DATABASE_URL",
    "KM_TIMESERIES_READONLY_PASSWORD",
)


def main() -> int:
    missing = [name for name in REQUIRED if not os.getenv(name)]
    if missing:
        print("TIMESERIES_PREPROD_PREFLIGHT_FAIL missing=" + ",".join(missing))
        return 2
    port = int(os.getenv("KM_PGADMIN_PORT", "5050"))
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            print(f"TIMESERIES_PREPROD_PREFLIGHT_FAIL pgadmin_port_in_use={port}")
            return 2
    free = shutil.disk_usage(Path.cwd()).free
    minimum = int(os.getenv("KM_TIMESERIES_MIN_FREE_BYTES", str(5 * 1024**3)))
    if free < minimum:
        print("TIMESERIES_PREPROD_PREFLIGHT_FAIL insufficient_disk")
        return 2
    if os.getenv("KM_CSIT_NOTIFICATION_ENABLED", "false").lower() == "true":
        if os.getenv("KM_CSIT_NOTIFICATION_ELIGIBILITY") != "test-allow" or not os.getenv("KM_CSIT_NOTIFICATION_AUTH_TOKEN"):
            print("TIMESERIES_PREPROD_PREFLIGHT_FAIL receiver_not_test_scoped")
            return 2
    print("TIMESERIES_PREPROD_PREFLIGHT_PASS secrets=present pgadmin_port=available disk=available receiver=bounded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
