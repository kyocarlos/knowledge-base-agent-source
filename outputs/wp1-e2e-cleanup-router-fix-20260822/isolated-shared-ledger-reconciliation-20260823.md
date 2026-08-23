# WP1 Isolated Shared-Ledger Reconciliation

Date: 2026-08-23

## Candidate

- Source: `e8455db7f36398995c0ec51647aff21aa4df3925`
- Release: `wp1-e2e-cleanup-router-fix-20260822-r1`
- Image: `sha256:f3290d5d594d20aa35e2b3799675f86a9dc615a01063acfa9efd8097bc710cf0`
- Environment: isolated shadow only
- Production touched: `false`
- Secrets included: `false`

## Shared Ledger Gate

The isolated Compose rendering explicitly set the same absolute path for `web`,
`search_worker`, `ingest_worker`, and `beat`:

`KB_JOB_LEDGER_PATH=/app/data/job-ledger.sqlite3`

All four services rendered the same path and mounted the same shared data volume
at `/app/data` and `/home/da40_ai_gb10/knowledge-base/data`. Runtime `stat`
evidence was identical for every service:

`/app/data/job-ledger.sqlite3|66306|64785378|16384`

This verifies the same device/inode/size, not merely equal environment strings.
The application fallback was not used.

## Register, Claim, and Lease Lifecycle

Synthetic run `TR-E2E-WP1-SHARED-20260823-222709-unique` registered successfully.
The ingest worker read the same ledger row and claimed it successfully. The
worker completed the job with terminal state `succeeded`.

The in-flight shadow drill additionally captured a running lease with an owner,
attempt 1, a lease expiry and updated timestamp, then killed the worker during
execution. Recovery sweep redelivered the job. The final row was `succeeded`,
attempt 2, recovery count 1, owner cleared, lease expiry zero, and completion
timestamp present.

## Recovery, Idempotency, and Cleanup

- Worker restart/recovery: PASS
- In-flight redelivery: PASS
- Attempts: 2
- Redis SETNX side effect count: 1
- Duplicate side effect prevented: PASS
- Upload/Ingest terminal completion: PASS
- Cleanup dry-run: HTTP 200
- Cleanup apply: HTTP 200
- Active task count after cleanup: 0
- Residual count: 0
- Post-cleanup health: PASS

## Conclusion

Root cause A, production configuration/path mismatch, is closed by this
isolated validation. No JobLeaseStore business logic was changed. Production
remains `NO-GO`; this evidence only establishes readiness for a new supervisor
Production Preflight review. No production retry, deployment, migration,
restore, WP2 work, or real-instrument operation was performed.

The first in-flight attempt failed only because the temporary test harness
referenced a non-existent `job_lease.py` mount. The harness was corrected and
the rerun passed; this is recorded for audit transparency and is not a
candidate/runtime failure.
