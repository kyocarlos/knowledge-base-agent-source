# WP1 In-flight Recovery Final Shadow Evidence

## Result

**PASS for application-level durable lease recovery in isolated shadow.**

The original Celery Redis redelivery behavior remained unreliable, so the
shadow flow now uses the application-level SQLite lease ledger. The worker
claims a short lease, is killed while the job is running, and a recovery
sweeper atomically changes the expired lease back to queued and republishes
the same `job_id`.

## Assertions

- Worker killed while job was in-flight: PASS
- Lease expiry detected and recovered: PASS
- Same `job_id` republished: PASS
- Attempt count: `1 -> 2`
- Final ledger status: `succeeded`
- Duplicate side effect count: `1`
- Cleanup: PASS
- Production touched: `false`

Evidence SHA-256:
`5db86c8016c75ca4880e0825d67ff08ef8f9871723a770b4882ef5f5280f9f8a`

Machine-readable evidence:
`outputs/inflight-job-recovery-final-shadow-20260820.json`

## Boundary

This proves the new application-level lease/recovery mechanism in isolation;
it does not claim that native Redis unacked redelivery is reliable. The next
required step is integrating lease registration, claim, completion and
worker-ready recovery into the real ingest task path, followed by application
idempotency and concurrency tests.
