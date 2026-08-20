# WP1 In-flight Recovery Diagnosis - 2026-08-20

## Finding

The effective Celery broker transport configuration reported
`visibility_timeout=5`, and Redis contained an `unacked_index` entry for the
in-flight task after the worker container was killed. A replacement worker
started successfully. One recovery kick and then twelve recovery kick tasks
were consumed, but the original task was still not redelivered.

## Evidence

- `effective_visibility_timeout`: `5`
- Redis keys: `unacked`, `unacked_index`
- `attempts`: `1`
- `completed_after_recovery`: `false`
- `redelivery_verified`: `false`
- `production_touched`: `false`
- Evidence SHA-256: `0979d6b1375e85f42d3d535af1cd800e4860d75a403c4ba6548b9e93479b19c5`

Machine-readable record:
`outputs/inflight-job-recovery-diagnosis-20260820.json`

## Decision

This remains a WP1 blocker. The evidence does not justify changing production
Celery/Redis configuration or manually requeueing jobs. The next engineering
change must identify the effective Kombu Redis `restore_visible` behavior or
replace it with an explicitly durable job lease/recovery mechanism, followed
by a fresh in-flight run with a unique task ID.
