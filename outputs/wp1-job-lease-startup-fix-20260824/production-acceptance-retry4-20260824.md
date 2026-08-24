# Production Acceptance Retry 4

## Result

Production acceptance **FAIL** at the deployment identity gate. The deployment was stopped before any synthetic write. The approved rollback completed successfully and restored the previous production baseline.

## Candidate

- Source: `4042284c23f2076e16a476f2426ec1f1ca73f7b4`
- Release: `wp1-job-lease-startup-fix-20260824`
- Image: `sha256:ed09a772cae7ddcb8251dac59f4e1921e6da24642bb4b7708b912edd97db2ea6`
- Deployment window: `2026-08-24T09:31:30+08:00` to `2026-08-24T09:31:34+08:00`

## Failure Diagnosis

The candidate web container configured four Uvicorn workers, but all four failed during application import. The traceback identifies `KM_BUILD_TIMESTAMP` containing `+08:00` as unsupported by the runtime configuration validator. This is a candidate runtime metadata/configuration validation failure, not a `database is locked` failure. `/health` and `/api/v1/version` returned HTTP 502 through Nginx, so no write-enabled acceptance step was started.

The four services had the planned shared ledger path and consistent mount/file identity before the gate stopped. Register/claim, lease, ingest, cleanup, and synthetic E2E were not run. No source code was modified during deployment.

## Temporary Identity

The temporary identity was additive and existing registry entries were preserved. It was removed as part of rollback. A post-removal authentication probe returned HTTP 403. Credential material and hashes are not present in this evidence.

## Rollback

- Result: **PASS**
- Checkpoint: `/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946`
- Checkpoint SHA-256: `18f0f3ff7f5652ad72b45d8ddc497ef8f7ece34b2de9a822ed7436fe0d719d3f`
- Rollback target: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Completed: `2026-08-24T09:32:08+08:00`
- Post-rollback health: PASS
- Celery nodes: 2
- Active/reserved/scheduled tasks: 0
- Queues: 0

No synthetic data was created, so cleanup was not required. Production writes, migration, restore, and real-instrument access were all false.

## Final Gate

`Production Gate = NO-GO`. Do not retry production or modify the approved source in place. Open a separate reviewed fix cycle for release metadata validation, then rebuild and revalidate an exact-source candidate before requesting another Production GO review.

Machine-readable details are in `production-acceptance-retry4-20260824.json`.
