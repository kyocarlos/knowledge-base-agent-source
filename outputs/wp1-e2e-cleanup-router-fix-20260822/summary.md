# WP1 Isolated Write Smoke Summary

## Candidate

- Source: `e8455db7f36398995c0ec51647aff21aa4df3925`
- Release: `wp1-e2e-cleanup-router-fix-20260822-r1`
- Image: `sha256:f3290d5d594d20aa35e2b3799675f86a9dc615a01063acfa9efd8097bc710cf0`
- Build timestamp: `2026-08-22T23:32:27+08:00`
- Synthetic run: `TR-E2E-WP1-CLEANUP-FIX-20260822-234514-bf02b7bd`

## Controlled Smoke

PASS: Health, Search, report agent self-read, shared ledger, Upload/Ingest,
duplicate submission deduplication, worker completion, approve/read, cleanup,
post-cleanup Health, and final service state. The four application services
were running before teardown. Upload returned 202; duplicate upload returned
202 with `duplicate=true`; agent self-read returned 200; approval returned 200;
ingest reached `completed`; cleanup dry-run/apply returned 200; the submission
returned 404 after cleanup; residual count was 0.

The complete redacted probe response is in `controlled-write-smoke.json`.

## Reliability Evidence

Using the same candidate image, isolated drills passed:

- Worker failure/restart recovery: `recovery_verified=true`
- In-flight redelivery: `redelivery_verified=true`, attempts=2,
  side_effect_count=1
- Application idempotency: one live owner and one side effect
- Redis reconnect/SETNX idempotency: value survived restart and duplicate
  SETNX was rejected

## Boundary

`production_touched=false`. No production deployment, production write,
migration, destructive restore, or real instrument access was performed.
Production Gate remains `NO-GO` pending supervisor Production Redeployment
Preflight Refresh.
