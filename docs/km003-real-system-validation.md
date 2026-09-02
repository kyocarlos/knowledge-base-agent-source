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
- `USER_VISIBLE_VALIDATED`: PASS (approved Search API entrypoint)
- `KM003`: DONE for the approved alternative user-visible entrypoint.

## User-visible validation checkpoint

On 2026-09-02, the disposable runtime completed the real Search API portion of
the user-facing flow. After v2 was published, a real v3 publish attempt
returned HTTP 409 from the isolated Neo4j store visibility gate; v3 remained
`ready`, v2 remained current, and the subsequent Search API result contained
only document version `2.0.0` for the validation document. Qdrant and Neo4j
package identity checks remained consistent.

The supervisor-approved alternative user-visible entrypoint was then validated
through the real `/search` task flow. After the isolated runtime was restored,
the v2-only query returned `completed` with only `document_version=2.0.0`
sources and complete package/document/chunk identity. The v3-only query after
the failed publish also returned only v2; the v3 registry record remained
`ready` and `is_current=false`. Qdrant and Neo4j both contained the matching
v1/v2 package identities, with v1 `superseded` and v2 `published/current`.
Sanitized details are in
`docs/evidence/km003-user-visible-runtime-20260902.json` and
`outputs/km003-user-visible-validation-20260902/alternative-api-evidence.json`.

Production deployment was not performed.
