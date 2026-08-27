# WP1 Production Acceptance Final Review – Post-Nginx-Activation

## Result

- Production acceptance: **FAIL before synthetic acceptance**
- Rollback: **PASS**
- Production Gate: **NO-GO**
- Candidate application regression: **NO EVIDENCE**

## Candidate

- Source: `914d7c829269779f13c47d71ebd27ecb9dde84ec`
- Release: `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Image: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`
- Build timestamp: `2026-08-26T15:21:36+08:00`

## Readiness Failure

The direct candidate backend became healthy and returned exact source/release/image/build metadata. The bounded readiness ran for 120 seconds with 60 attempts at a 2-second interval. Formal ingress `/health` and `/api/v1/version` did not return a valid response. No synthetic write was started.

Root cause is recorded as **NOT_DETERMINABLE** from this capture. The diagnostic bundle is preserved at `outputs/ingress-failure-diagnostics/20260827-103336/`.

## Rollback

The approved rollback path restored the baseline application image `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`. Post-rollback Health, WP0/WP1 gates, Celery (2 nodes), tasks, and queues passed.

The controlled application-service recreate was attempted and then rolled back. No synthetic/business write, stuck-task mutation, Redis/ledger mutation, migration, restore, or real-instrument operation occurred.
