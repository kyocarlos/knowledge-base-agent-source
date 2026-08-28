# WP1 Production Acceptance Final Review

## Result

`Production Acceptance = FAIL before synthetic acceptance`.
`Rollback = PASS`. `Production Gate = NO-GO`.

The approved candidate was recreated only for the four application services. Direct backend readiness passed, but formal ingress `/health` and `/api/v1/version` did not return a valid response after 60 attempts over 120 seconds. Synthetic Upload/Ingest, duplicate/idempotency, cleanup, and all other acceptance writes were not started.

## Candidate

- Source: `914d7c829269779f13c47d71ebd27ecb9dde84ec`
- Release: `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Image: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`
- Build timestamp: `2026-08-26T15:21:36+08:00`

## Readiness

- Direct backend first success: `2026-08-27T01:09:15.109242+00:00`.
- Formal ingress first success: none.
- Bounded polling: `60` attempts, `2` seconds interval, `120` seconds timeout.
- Diagnostic bundle: `outputs/ingress-failure-diagnostics/20260827-091113`.
- Readiness evidence: `outputs/deployment-readiness/20260827-090913.json`.

## Rollback

Rollback completed successfully to the approved checkpoint:

`/home/da40_ai_gb10/knowledge-base/outputs/current-runtime-checkpoints/pre-deploy-wp1-lease-current-runtime-20260826-145148`

Checkpoint manifest SHA-256: `1801a67e87c5f1019587052e4b1e4d53f258334c3f806ab829c11ca889c3a4e5`.

Post-rollback application image is `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`. Health, WP0/WP1 runtime gates, Celery 2 nodes, active/reserved/scheduled tasks, and queues are healthy/empty.

## Safety

No synthetic business data was written. The original stuck task was not retried or modified. No Redis/ledger mutation, migration, restore, WP2 deployment, or real instrument operation occurred. No secrets are included.

Next action is a read-only `WP1 Ingress Failure Diagnostic Bundle Review`; do not retry deployment until the ingress failure is diagnosed and separately approved.
