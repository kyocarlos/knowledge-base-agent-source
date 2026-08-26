# WP1 Ingest Lease Reconciliation

This fix closes the state gap where an ingest worker received a Celery task,
failed to claim the application lease, and returned `SUCCESS` while the Redis
task remained `queued`.

## Decision contract

The worker performs a read-only diagnosis after `JobLeaseStore.claim()` returns
no lease:

- `already_completed`: return the completed state idempotently.
- `active_lease`: do not steal the lease; use Celery retry.
- `ledger_record_missing` or inconsistent state: mark the ingest task as
  terminal `failed`, record a reconciliation event, and do not retry blindly.

The reconciliation path never deletes ledger rows, changes a task to
completed, bypasses idempotency, or forces cleanup. A re-submit requires an
operator-approved, separately identified request after the underlying
configuration or state problem is resolved.

## Scope

This is WP1 runtime reliability work. It preserves the existing upload,
conversion, Neo4j/Qdrant ingest and report contracts and does not change WP2,
production data, or the Anritsu agent.
