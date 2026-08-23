# Production Acceptance Retry 3

Date: 2026-08-23
Result: **FAIL, rolled back successfully**

## Candidate and Deployment

- Source: `e8455db7f36398995c0ec51647aff21aa4df3925`
- Release: `wp1-e2e-cleanup-router-fix-20260822-r1`
- Image: `sha256:f3290d5d594d20aa35e2b3799675f86a9dc615a01063acfa9efd8097bc710cf0`
- Planned ledger path: `/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3`
- Four-service path/mount preflight: PASS
- Deployment window: `2026-08-23T23:50:36+08:00` to `2026-08-23T23:51:23+08:00`

## Failure and Stop

The first identity gate returned HTTP 502 for Health and Version. Web logs
showed `sqlite3.OperationalError: database is locked` during
`JobLeaseStore` WAL initialization in one Uvicorn child process. Acceptance
stopped immediately; no synthetic run, Upload/Ingest, Report Review, or
production business write was started.

This is recorded as a production runtime startup/configuration concurrency
blocker. No source code was changed during this run.

## Temporary Identity

The temporary E2E identity was additive and the existing registry was preserved.
Rollback removed the temporary runtime configuration. A post-rollback request
using the temporary identity returned HTTP 403, confirming authentication was
no longer accepted. Credential material and hashes were not written to Git or
evidence.

## Rollback

- Checkpoint: `/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946`
- Checkpoint SHA-256: `18f0f3ff7f5652ad72b45d8ddc497ef8f7ece34b2de9a822ed7436fe0d719d3f`
- Rollback target: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Rollback result: PASS

## Final State

After rollback, Health, WP0/WP1 gates, Celery (2 nodes), queues, and active /
reserved / scheduled task checks all passed. Production is back on the
approved baseline. Production Gate remains **NO-GO** and WP1 Final Closure was
not reached.

The next action is a separate diagnosis/fix cycle for SQLite WAL initialization
concurrency, followed by new CI, image identity, isolated validation, and a
new Production GO Review. No third acceptance retry should be attempted before
that review.
