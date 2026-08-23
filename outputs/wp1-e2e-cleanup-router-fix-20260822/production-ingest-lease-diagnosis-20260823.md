# Production Ingest Lease Diagnosis

Date: 2026-08-23 (Asia/Taipei)

This is a read-only diagnosis. No production row, Redis task state, lease,
queue, database, or source code was modified.

## Target State

- Run ID: `TR-E2E-WP1-PROD-RETRY-20260823-095504-unique`
- Submission: `report_20260823_015605_548beca0`
- Ingest task: `ingest_20260823_015605_be828d38`
- Submission state: `queued`
- Redis task state: `queued`, `started_at=null`, `ingested=false`
- Celery queue lengths after rollback: all inspected queues were `0`

The PostgreSQL submission and Redis task state agree that the task never
reached a terminal state. The worker receipt and `lease claim false` message
were present in the acceptance evidence/log. The current runtime cannot prove
whether the broker acknowledged or redelivered the task after rollback.

## Root Cause

Classification: **A — production configuration/path mismatch**.

The reviewed candidate's `JobLeaseStore` reads `KB_JOB_LEDGER_PATH` and falls
back to the relative path `data/job-ledger.sqlite3` when the variable is absent.
The live production Compose used for the deployment did not declare
`KB_JOB_LEDGER_PATH`. It mounted uploads and report staging, but not a shared
container path for the relative ledger file. Therefore the web container could
register the job in its private container filesystem while the ingest worker
looked in a different private filesystem and returned no lease. The claim
function intentionally returns no lease for a missing row, a succeeded row, or
a live lease owned by another worker, and its warning does not distinguish
these cases.

The candidate branch Compose does declare an absolute shared-data path, but the
production attempt used the live Compose with an image override. This is a
deployment/configuration attribution issue, not proof of a code defect.

## Lease Forensics Boundary

The candidate containers were rolled back and removed under the approved
rollback procedure. Consequently, the candidate SQLite ledger row, owner,
acquired time, heartbeat, expiry, attempt count, and inode cannot be recovered
from the current baseline. These fields are explicitly `NOT_DETERMINABLE`, not
guessed. There is no evidence that a stale lease existed before the retry.

## Cleanup

Cleanup dry-run identified one active task. Cleanup apply returned HTTP 409 and
the active-task protection was preserved. No manual terminalization, ledger
deletion, or task-state edit was performed. Cleanup completion therefore
remains **BLOCKED**.

## Recommended Next Step

Run an isolated/shadow reconciliation using one explicit absolute ledger path
mounted identically into web, search worker, ingest worker, and beat. Capture
the path and inode from every service, then prove register -> claim -> terminal
completion/recovery -> cleanup. Only after that evidence passes should a new
production approval be requested. Do not retry production or change source in
this diagnosis cycle.
