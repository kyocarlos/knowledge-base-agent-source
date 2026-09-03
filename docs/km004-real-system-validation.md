# KM004 Real-System Validation

## Scope

KM004 extends the existing KM002 lifecycle and KM003 re-ingest path. It does
not introduce another revision state machine. Publishing remains registry-last:
both store visibility updates must succeed before the durable revision pointer
changes.

The implementation adds a sanitized `StoreConsistencyError` and a structured
HTTP 409 detail for the lifecycle transition API. The diagnostic contains only
operation names, store outcomes, partial-write state, and rollback state.

## Source and focused validation

- Base: KM003 merge commit `44f31e072aab58ededed68eb2e669ecd4824bcc7`.
- Branch: `phase1-km004-store-consistency-20260902`.
- `tests/test_knowledge_lifecycle.py` and `tests/test_revisioned_reingest.py`:
  `8 passed`.
- Python compile: PASS.
- `git diff --check`: PASS.

## Real integrated runtime

Disposable Compose project: `km004`; application image:
`km004-store-consistency:20260902`.

- Web, Celery search/ingest/beat, Redis, PostgreSQL registry, Qdrant, Neo4j
  and Nginx were running.
- `/health`: HTTP 200.
- `/api/v1/version`: HTTP 200.
- Image ID: `sha256:9540ecac4a84309918b1b9c3cc3776a9f5a1ca01ae102d42405e106ce6b59f2c`.
- Production containers, database and files were not used or modified.

## Real-store scenarios

The harness created unique KM004 revisions in the disposable SQLite registry,
real Qdrant collection, and real Neo4j nodes. Failure injection was limited to
one visibility adapter at a time.

| Scenario | Failure result | Durable result | Retry |
| --- | --- | --- | --- |
| Qdrant success / Neo4j failure | `partial_write=true`, `rollback_complete=true`; Qdrant applied, Neo4j failed | v2 remained `ready`, v1 remained current; Qdrant compensation passed | v2 became published/current in both stores |
| Neo4j success / Qdrant failure | `partial_write=true`, `rollback_complete=true`; Neo4j applied, Qdrant failed | v2 remained `ready`, v1 remained current; Neo4j compensation passed | v2 became published/current in both stores |

After each retry, Qdrant and Neo4j reported the same package identity and
`published/current` visibility. Harness records were deleted from the
disposable stores after validation.

## Status

`IMPLEMENTED = PASS`, `INTEGRATED = PASS`, and
`RUNTIME_VALIDATED = PASS` in the isolated production-compatible runtime.
`USER_VISIBLE_VALIDATED = PASS`: the official lifecycle transition API returned
a sanitized HTTP 409 during an isolated Neo4j failure; Search returned only v1.
After Neo4j recovery, the official retry returned HTTP 200 and Search returned
only v2 as the current revision. Evidence is recorded in
`docs/evidence/km004-user-visible-runtime-20260903.json`.
KM004 is complete through IMPLEMENTED, INTEGRATED, RUNTIME_VALIDATED and
USER_VISIBLE_VALIDATED. Production deployment is not authorized.

No raw credentials, environment dumps, database passwords, tokens, or private
keys are included in the evidence.
