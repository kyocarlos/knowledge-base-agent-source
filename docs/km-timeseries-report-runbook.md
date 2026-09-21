# KM-TS-REPORT-V1 runbook

## Isolated verification

```bash
docker compose -p km-ts-report-ci -f docker-compose.ci.yml up -d --wait
export KM_TIMESERIES_DATABASE_URL=postgresql://km_ci:ci-timescale-password@127.0.0.1:15433/km_ci
export KM_TIMESERIES_READONLY_URL=postgresql://km_ts_readonly:ci-timescale-readonly@127.0.0.1:15433/km_ci
python scripts/ci_timeseries_report.py
KM_PGADMIN_URL=http://127.0.0.1:15050 python scripts/verify_pgadmin.py
KM_TIMESERIES_DATABASE_URL=postgresql://km_ci:ci-timescale-password@127.0.0.1:15433/km_ci python scripts/cleanup_timeseries_evidence.py
docker compose -p km-ts-report-ci -f docker-compose.ci.yml down -v
```

The verification creates a disposable real `.xlsx`, parses it with the
existing validator, applies the versioned migrations, writes three samples,
checks the Timescale hypertable catalog, repeats the import, reads as the
read-only role, and proves that INSERT is denied. Its output is sanitized.

## Deployment boundary

Production migration, historical backfill, secret provisioning, container
restart, CSIT calls, and pgAdmin public exposure require a separate approved
change. This PR does not execute them.
