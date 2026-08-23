# Production Acceptance Attempt

Date: 2026-08-23 (Asia/Taipei)

## Candidate and Identity Gate

- Source: `e8455db7f36398995c0ec51647aff21aa4df3925`
- Release: `wp1-e2e-cleanup-router-fix-20260822-r1`
- Image: `sha256:f3290d5d594d20aa35e2b3799675f86a9dc615a01063acfa9efd8097bc710cf0`
- Deployment start: `2026-08-23T09:35:24+08:00`
- Health: PASS, HTTP 200
- `/api/v1/version`: PASS; commit, release ID, image digest and build timestamp matched.

## Acceptance Result

Synthetic run: `TR-E2E-WP1-PROD-20260823-093524-unique`

Search, report agent health, upload, and duplicate deduplication passed. The
report self-read then returned HTTP 403. No approve, ingest worker, recovery,
in-flight, or application-idempotency acceptance was counted after this failure.

The failure is a production configuration boundary issue: the temporary E2E
agent identity was configured for the E2E upload path, while the self-read route
uses the regular agent registry. No source code was changed during deployment.

The created synthetic submission was cleaned immediately:

- files deleted: 2
- report submissions deleted: 1
- ingest records: 0
- Neo4j nodes: 0
- Qdrant points: 0
- residual count: 0

## Rollback

Per the mandatory acceptance failure rule, rollback was executed with the
approved checkpoint:

```text
python3 scripts/rollback_pre_wp01.py --checkpoint /home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946 --execute --confirm-production PRE_WP01_ROLLBACK
```

Rollback PASS. Final web image returned to
`sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`.
After worker startup settled, Health was HTTP 200, Celery had 2 nodes, and
queues were empty.

## Gate

Production acceptance: `FAIL`

Production Gate: `NO-GO`

The candidate is not accepted for production. A retry requires a separately
approved production E2E agent-registry configuration; no configuration change
was made after rollback.
