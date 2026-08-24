# PR #16 Production Acceptance

## Candidate

- Source: `703075efe862736cffe5159edfcb3b1940c5ae09`
- Release: `wp1-metadata-validation-fix-20260824-r2`
- Image: `sha256:8f009d19a8bfec29736cfb08b1175795aaabdc44449bf298e29d5c8974ed129c`
- Build timestamp: `2026-08-24T10:09:35+08:00`
- Deployment: `2026-08-24T10:39:09+08:00` to `2026-08-24T10:39:14+08:00`

## Identity and Ledger Gates

The four application services used the exact shared path
`/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3` and the same shared
mount. Ledger device/inode was `66306/4492816`; the initialization lock was
`/home/da40_ai_gb10/knowledge-base/data/.job-ledger.sqlite3.init.lock` with
device/inode `66306/4492817`. Four Uvicorn workers started, no `database is
locked` was observed, Health was PASS, and `/api/v1/version` returned the exact
candidate identity including the RFC3339 timestamp.

## Controlled Synthetic Acceptance

Run ID: `TR-E2E-WP1-PR16-PROD-20260824-103649-2738b350`

- Search: PASS
- Report agent health: PASS
- Upload: PASS
- Duplicate submission: PASS; second response reported `duplicate=true`
- Report self-read: PASS
- Report approve/read: PASS
- Register, claim, lease completion: PASS
- Worker completion: PASS
- Cleanup dry-run/apply: PASS
- Active tasks after cleanup: `0`
- Synthetic residual count: `0`
- Post-cleanup Health: PASS

Worker recovery, in-flight redelivery, Redis reconnect/SETNX, and the broader
application idempotency drill remain backed by the accepted isolated candidate
evidence under `outputs/wp1-metadata-validation-fix-20260824/isolated/`.
They were not re-induced destructively in production; production checks added
here cover completion, duplicate submission prevention, and post-cleanup state.

## Temporary Identity Cleanup

The temporary additive identity was removed after acceptance. Existing registry
entries were preserved, E2E write and cleanup modes were disabled, regular
authentication with the temporary identity returned HTTP 403, and the E2E
endpoint returned HTTP 404 because E2E mode was disabled. No credential or hash
material is present in this evidence.

## Final Status

- Production candidate remains deployed and healthy.
- Celery: 2 nodes; active/reserved/scheduled tasks and queues: 0.
- Rollback was not required; approved rollback readiness remained PASS.
- Migration, restore, WP2 deployment, unrestricted production writes, and real
  instrument access were not performed.
- Production acceptance: `PASS`.
- WP1 100% closure remains subject to supervisor final review; PR #16 remains
  Draft and must not be merged by this operation.
