# WP1 Production Deployment Boundary Evidence

This record distinguishes an observed host deployment from PR #9 acceptance.
It contains no credentials, tokens, runtime databases, or private configuration.

## Decision

- PR #9 reviewed source: `fefcc857ee3d3e8531154b5f3b98f38878c93423`
- Observed deployed release source: `5c7ea2dac186bd906a4d7df64db25d55133674cc`
- Because these are different commits, the observed deployment is **not** PR #9
  production acceptance.
- Production Gate remains **NO-GO** and PR #9 remains Draft.

## Evidence

- Live tag: `kb-wp01-live:65b490df126a-20260821110939`
- Container start observed: `2026-08-21T11:09:44+08:00`
- Exact deployment end time: **PENDING**, because the original deployment command did
  not emit a machine-readable end timestamp.
- Previous checkpoint:
  `/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-wp01-maintenance-20260821-102314`
- Checkpoint SHA-256:
  `65e167878d88bfddb7dd1655d485ed5fcbbac0a5883bdc550d14d4bcf42b0327`
- Shadow rollback: PASS, from
  `/home/da40_ai_gb10/kb-pre-wp01-drills/20260821_100839/rollback-drill.json`.

## Gate results

Health/Version, read-only Chat, WebSocket, Celery worker/queue, JobConfig, Beat,
Qdrant and Ollama checks were observed as passing. Existing isolated worker
recovery and application idempotency evidence remains valid.

Upload/Ingest, Report Review, a deployment-specific synthetic `run_id`, and
deployment-specific cleanup were not recorded in this deployment evidence. They
remain `PENDING`; no write-path success is inferred from HTTP health or queue
readiness.

The machine-readable record is
[`WP1-production-deployment-20260821.json`](WP1-production-deployment-20260821.json).
