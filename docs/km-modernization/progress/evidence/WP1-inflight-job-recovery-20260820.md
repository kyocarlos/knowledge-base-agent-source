# WP1 In-flight Job Recovery Evidence

## Result

**FAIL / BLOCKED: worker-loss redelivery was not demonstrated.**

This is a deliberate failure record, not a completion claim. An isolated
Celery/Redis shadow job was confirmed in-flight (`attempt=1`), the worker
container was killed, and a fresh worker was started. Redis retained the
`unacked` and `unacked_index` structures, but the job was not redelivered
within the 60-second recovery window.

Observed state:

- `completed_after_recovery=false`
- `attempts=1`
- `side_effect_count` absent
- `redelivery_verified=false`
- `duplicate_side_effect_prevented=false` because completion never occurred
- `production_touched=false`

Evidence SHA-256:
`876d5f55fc8bb8c0fc47840ab459cfa5f8dd8a65b86791f84e0368b155393864`

Machine-readable evidence:
`outputs/inflight-job-recovery-shadow-20260820.json`

## Required follow-up

Do not manually requeue this test as a pass and do not change production
Celery/Redis settings from this evidence. Diagnose the effective Kombu Redis
visibility/ack configuration, then repeat with a fresh run ID after the
redelivery contract is corrected. WP1 remains conditional and this gate is
pending.
