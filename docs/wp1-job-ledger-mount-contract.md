# WP1 Shared Job-Ledger Mount Contract

All services that import or use `JobLeaseStore` must resolve the same
`KB_JOB_LEDGER_PATH` and the same physical host storage identity.

Required consumers:

- `web`: registers the domain `ingest_task_id` before Celery enqueue.
- `celery_search_worker`: imports the shared task module and initializes the
  lease store.
- `celery_ingest_worker`: claims and completes/fails the domain task.
- `celery_beat`: imports the shared task module and initializes the lease store.

Logical path equality is necessary but insufficient. The preflight validator
must compare each container's resolved host source, device/inode, and SHA-256
for the ledger file. Any mismatch is a fail-closed result before acceptance or
deployment. The validator is read-only and does not repair or merge ledgers.

The producer contract is `register(ingest_task_id)` before `apply_async()`;
the worker claims the same `ingest_task_id`. A shared physical ledger is
therefore required for the claim to succeed.
