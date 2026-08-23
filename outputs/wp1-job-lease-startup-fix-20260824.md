# WP1 Job Lease Startup Fix Evidence

## Scope

This independent fix cycle addresses the Retry #3 startup failure:
`sqlite3.OperationalError: database is locked` while multiple Uvicorn
workers initialized `JobLeaseStore` and executed WAL/schema setup.

The fix serializes only WAL/schema initialization with a lock file adjacent to
the configured ledger. Job lease registration, claim, retry, completion, and
idempotency behavior are unchanged.

## Candidate

- Source: `4042284c23f2076e16a476f2426ec1f1ca73f7b4`
- Local image: `kb-wp1-job-lease-startup-fix:local`
- Local image ID: `sha256:29f210334bc4d72d7b83f660799a7bfe575274bbd41fe337ac55d15b1525c58b`
- Registry digest: pending; no registry push performed

## Validation

- Four independent processes initialized the same SQLite ledger: **PASS**
- Four-worker Uvicorn startup: **PASS**; all workers reached application startup
- `database is locked` during startup: **not observed**
- Python compile validation: **PASS**
- Host pytest: **NOT RUN**, because pytest is not installed
- Minimal container probe emitted the existing missing `config.yaml` scheduler
  warning; the application still reached startup and this warning is outside
  the SQLite concurrency test scope.

## Safety Boundary

Production was not deployed, restarted, or written. No migration, restore,
WP2 work, real-instrument access, or secret material was used. A new
production retry is not authorized by this evidence.
