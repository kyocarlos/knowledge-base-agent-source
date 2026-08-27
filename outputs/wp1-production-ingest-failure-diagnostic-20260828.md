# WP1 Production Ingest Failure Diagnostic Review

## Decision

Production acceptance failed during ingest. Rollback passed. Production Gate remains `NO-GO`.

The persisted terminal error is the generic application error `攝入文件失敗`. The lower-level cause cannot be determined after rollback because the worker failure-window logs and detailed exception evidence were not retained. The evidence therefore does not classify this as a candidate or application regression.

## Attempt

- Run ID: `TR-E2E-WP1-PROD-IDENTITY-20260827-163555-6937da3f`
- Submission: `report_20260827_163838_cbe0d655`
- Ingest task: `ingest_20260827_164650_dccd36af`
- Celery task: `33496dd6-9f5d-49ab-b5ed-c4ba98271408`
- Candidate: `914d7c829269779f13c47d71ebd27ecb9dde84ec`
- Image: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`

The run ID was reused from a prior production attempt. This violated the production uniqueness hard gate, so the acceptance is procedurally invalid in addition to the ingest failure. The current runner does not yet implement an automatic prior-production-run exclusion gate.

## Reconciled State

Upload returned `202`, duplicate detection returned `duplicate=true`, Report self-read returned `200`, and approval returned `200`. The report registry, Redis task state, and SQLite ledger all ended in a failed terminal state:

- Registry: `ingest_failed`, error `攝入文件失敗`.
- Redis: `failed`, `ingested=false`, progress `0`.
- Ledger: `failed`, attempt `1`, owner `null`, lease-until `0`, recovery count `0`.
- No stale lease, foreign owner, lease timestamps, ACK/redelivery state, or lower-level worker exception can be proven from retained evidence.

The shared ledger path was the explicit production path `/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3`; path consistency and candidate metadata were PASS at readiness. Approval was complete before ingest. Production and isolated fixture hashes differ because fixtures are generated per run; this is not evidence of content regression.

## Cleanup 503 Classification

Cleanup dry-run and apply both returned `503 E2E cleanup backend unavailable`. This is classified as `INDEPENDENT_CLEANUP_BACKEND_FAILURE` with medium confidence: the endpoint failed at its own backend-availability boundary, and there is no evidence that ingest caused the 503. The exact cleanup backend subcause remains undetermined. Residual count was not independently verified by the cleanup endpoint before rollback; it must not be reported as zero for this attempt.

## Rollback and Safety

Rollback to the approved persistent checkpoint passed. After rollback, Health and Version were HTTP `200`, Celery had 2 nodes, active/reserved/scheduled tasks were zero, and queues were empty. The temporary identity was rejected with HTTP `404`. No task retry, manual Redis/ledger mutation, migration, restore, WP2 deployment, real instrument access, or credential evidence occurred.

## Required Follow-up

Do not retry production from this diagnostic. Reproduce the ingest failure and cleanup backend behavior in isolated/non-production while retaining failure-window logs and detailed exception evidence. Separately add a pre-network/write run uniqueness gate that rejects any run ID present in prior production acceptance evidence and records `run_id_uniqueness_gate=PASS` only after the check succeeds.
