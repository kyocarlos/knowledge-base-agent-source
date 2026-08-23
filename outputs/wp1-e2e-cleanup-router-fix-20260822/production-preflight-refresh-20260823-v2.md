# Production Preflight Refresh v2

Date: 2026-08-23
Mode: read-only

## Result

Production Preflight Refresh: **PASS**

Production Gate: **NO-GO** until a separate supervisor Production GO decision.
No production deployment, restart, write, migration, restore, WP2 work, or
real-instrument operation was performed.

## Current Runtime

- Current web image: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Health: PASS
- WP0/WP1 runtime gates: PASS
- Celery nodes: 2
- Active/reserved/scheduled tasks: 0/0/0
- All inspected queues: 0

## Checkpoint and Rollback

- Checkpoint: `/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946`
- Checkpoint SHA-256: `18f0f3ff7f5652ad72b45d8ddc497ef8f7ece34b2de9a822ed7436fe0d719d3f`
- Checkpoint verification: PASS
- Rollback target: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Rollback target matches current runtime: `true`
- Rollback readiness: PASS
- Drift since checkpoint: `false`

## Candidate

- Source: `e8455db7f36398995c0ec51647aff21aa4df3925`
- Release: `wp1-e2e-cleanup-router-fix-20260822-r1`
- Image: `sha256:f3290d5d594d20aa35e2b3799675f86a9dc615a01063acfa9efd8097bc710cf0`
- Local candidate image exists: PASS
- Source/release/image identity: consistent

## Planned Shared Ledger Configuration

The next deployment must explicitly pin:

`KB_JOB_LEDGER_PATH=/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3`

The read-only rendered Compose check confirmed the same value for `web`,
`celery_search_worker`, `celery_ingest_worker`, and `celery_beat`. All four use
the same host data source mounted at:

`/home/da40_ai_gb10/knowledge-base/data`

The configuration does not rely on the application fallback. No secrets were
included in the rendered evidence.

## Temporary E2E Identity

The approved shadow procedure is additive runtime env injection using a 0600
temporary env file, followed by a controlled application-service restart. It
preserves the existing registry. After acceptance, remove the temporary env
and hash entry, reload/restart the required services, and verify the temporary
identity receives authentication rejection while the original registry entries
remain available. Credential material is excluded from evidence.

## Recommendation

The technical read-only preflight is ready for supervisor Production GO Review.
This record does not authorize deployment; Production Gate remains **NO-GO**.
