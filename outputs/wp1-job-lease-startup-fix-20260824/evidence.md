# WP1 Job Lease Startup Fix Candidate Evidence

## Candidate identity

- Source commit: `4042284c23f2076e16a476f2426ec1f1ca73f7b4`
- Release ID: `wp1-job-lease-startup-fix-20260824`
- Image tag: `kb-wp1-release:wp1-job-lease-startup-fix-20260824`
- Image ID: `sha256:ed09a772cae7ddcb8251dac59f4e1921e6da24642bb4b7708b912edd97db2ea6`
- Build timestamp: `2026-08-24T06:47:20+08:00`
- Registry digest: not pushed; separate approval required

## Startup race validation

The exact-source image was started with four Uvicorn workers. All four worker
processes started and reached application startup. No `database is locked`
message was observed. The 4-process direct initialization regression test also
passed.

## Shared ledger

All four application services used the explicit absolute path:
`KB_JOB_LEDGER_PATH=/app/data/job-ledger.sqlite3`.

The rendered runtime used the same shared data mount. Runtime probes from
`web`, `search_worker`, `ingest_worker`, and `beat` reported the same path and
device/inode identity (`device=66306`, `inode=70782489`).

## Full isolated smoke

The synthetic write-enabled smoke passed:

- Health and `/api/v1/version` identity
- Search
- Report agent self-read
- Upload/Ingest and worker completion
- Duplicate submission deduplication
- Report approve/read
- Lease register -> claim -> succeeded completion
- Worker recovery and in-flight redelivery
- Application idempotency and Redis reconnect/SETNX idempotency
- Cleanup dry-run/apply
- Active task count after cleanup: `0`
- Residual count: `0`
- Post-cleanup Health

All evidence is redacted and contains no token/hash credential material.

## Safety and gate

`production_touched=false`. No production deployment, restart, write,
migration, restore, WP2 work, or real-instrument action was performed.
The candidate can enter supervisor Production Preflight Review; it is not a
production deployment authorization.
