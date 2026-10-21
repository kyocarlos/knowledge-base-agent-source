#!/usr/bin/env python3
"""Validate three non-secret deployment env files before `docker compose up`.

This intentionally performs no Docker, database, or network mutation.
"""

from __future__ import annotations

import argparse
from pathlib import Path


REQUIRED = {
    "COMPOSE_PROJECT_NAME", "KM_INSTANCE_ID", "KM_HTTPS_PORT", "KM_TLS_CERT_PATH", "KM_TLS_KEY_PATH", "KM_REPORT_DB_NAME",
    "KM_REPORT_DB_USER", "KM_TIMESCALE_DB_NAME", "KM_TIMESCALE_DB_USER",
    "KM_CONTROL_DB_URL", "KM_CONTROL_PUBLIC_ORIGIN", "KM_CONTROL_NETWORK",
}
EXPECTED = {"test", "da40", "rd2"}


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number}: expected KEY=VALUE")
        key, value = line.split("=", 1)
        values[key] = value
    missing = REQUIRED - values.keys()
    if missing:
        raise ValueError(f"{path}: missing {sorted(missing)}")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("env_files", nargs=3, type=Path)
    args = parser.parse_args(argv)
    configs = [load_env(path) for path in args.env_files]
    ids = {config["KM_INSTANCE_ID"] for config in configs}
    if ids != EXPECTED:
        raise SystemExit(f"expected exactly {sorted(EXPECTED)}, got {sorted(ids)}")
    for field in ("COMPOSE_PROJECT_NAME", "KM_HTTPS_PORT", "KM_TLS_CERT_PATH", "KM_TLS_KEY_PATH", "KM_REPORT_DB_NAME", "KM_REPORT_DB_USER", "KM_TIMESCALE_DB_NAME", "KM_TIMESCALE_DB_USER"):
        values = [config[field] for config in configs]
        if len(values) != len(set(values)):
            raise SystemExit(f"{field} must be unique across Test, DA40, and RD2")
    for field in ("KM_CONTROL_DB_URL", "KM_CONTROL_PUBLIC_ORIGIN", "KM_CONTROL_NETWORK"):
        if len({config[field] for config in configs}) != 1:
            raise SystemExit(f"{field} must identify the same central Control plane")
    print("PASS: three distinct KM data-plane deployment definitions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
