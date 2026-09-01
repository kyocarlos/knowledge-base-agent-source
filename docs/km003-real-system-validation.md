# KM003 Real-System Validation

## Scope

KM003 adds non-destructive versioned re-ingest on top of the KM002
`knowledge_revisions` registry and lifecycle. The current revision is never
deleted before the replacement has completed processing and store writes.

Implementation commit: `f01a323`

## Source and integration

- `src/revisioned_reingest.py` coordinates processing/indexing, retryable draft
  state, and existing lifecycle publication.
- `src/ingest.py` exposes `reingest_document_revision` as the application
  integration boundary.
- No second revision registry or replacement state machine was introduced.

## Real runtime result

The disposable runtime used real FastAPI, Celery, Redis, Qdrant, Neo4j and the
existing SQLite revision registry. Sanitized evidence is in
`docs/evidence/km003-real-runtime-20260901.json`.

1. v1 was ingested, transitioned and published as current.
2. v2 was ingested as a draft/ready revision.
3. A real store visibility failure was injected before v2 publication.
4. v1 remained searchable through the real Search API.
5. The same v2 revision was retried through `reingest_revision`.
6. v2 became published/current and its Qdrant payload identity matched the
   Neo4j `Document` identity by `package_id` and `document_version`.
7. v1 became superseded and was absent from default Search results.

Runtime checks passed: health, Search API, durable registry, Qdrant, Neo4j,
production isolation, and sanitized evidence boundary.

## Completion status

- `IMPLEMENTED`: PASS
- `INTEGRATED`: PASS
- `RUNTIME_VALIDATED`: PASS
- `USER_VISIBLE_VALIDATED`: PENDING
- `KM003`: NOT DONE until the same v1/v2 failure/retry behavior is verified
  from `chat.html` or the approved user-facing entrypoint.

Production deployment was not performed.
