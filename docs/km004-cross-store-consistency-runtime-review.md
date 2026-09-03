# KM004 Cross-Store Consistency Runtime Review

## Review boundary

- Branch: `phase1-km004-store-consistency-20260902`
- PR: `https://github.com/kyocarlos/knowledge-base-agent-source/pull/43`
- Latest source commit: `d63c95cdc92102982444f76a1dd3829c66a5a376`
- Runtime: disposable production-compatible FastAPI/Celery/Redis/Qdrant/Neo4j/registry Compose stack
- Shared user entry baseline: `docs/phase1-main-user-entry-baseline.md`
- Production deployment: not authorized and not performed

KM004 reuses the KM001 package identity, KM002 lifecycle, and KM003
non-destructive re-ingest orchestration. It does not add another ingestion or
revision framework. The registry is advanced only after both store visibility
updates succeed.

## Runtime results

| Scenario | Result | User-visible / durable observation |
| --- | --- | --- |
| Normal Qdrant + Neo4j write | PASS | v1 publish returned HTTP 200; package/document/version identity was written to both stores and became published/current. |
| Qdrant success / Neo4j failure | PASS | lifecycle API returned HTTP 409 with sanitized store outcomes; partial write was detected, previous current remained searchable, and retry converged both stores before current switch. |
| Neo4j success / Qdrant failure | PASS | lifecycle runtime returned fail-closed outcome with rollback; previous current remained searchable and retry converged both stores before current switch. |

The focused real-store matrix is recorded in
`docs/evidence/km004-real-runtime-20260902.json`.

## Feature-specific user-visible validation

Using the official lifecycle transition API and `/search` API in a fresh
isolated runtime:

1. v1 was published/current and `/search` returned only v1.
2. v2 was ready. An isolated Neo4j failure caused HTTP 409. The response
   exposed only `operation`, `store_outcomes`, `partial_write`,
   `rollback_complete`, and `rollback_outcomes`; no secret material was
   present.
3. Search after the failure still returned v1 and did not return failed v2.
4. After Neo4j recovery, retry returned HTTP 200. Search returned only v2 as
   published/current and v1 was superseded.
5. Registry, Qdrant and Neo4j all reported matching package identity and
   visibility.

Detailed sanitized evidence:
`docs/evidence/km004-user-visible-runtime-20260903.json`.

## Completion status

- IMPLEMENTED: PASS
- INTEGRATED: PASS
- RUNTIME_VALIDATED: PASS
- USER_VISIBLE_VALIDATED: PASS (KM004-specific lifecycle/Search behavior)
- KM004: DONE pending supervisor final review
- Production touched: `false`
- Production database touched: `false`
- Secrets included: `false`

## Findings

- P1 `CROSS_STORE_PARTIAL_PUBLISH_CONSISTENCY_RISK`: CLOSED at runtime validation.
- P2 registry-update failure injection: technical debt, non-blocking.
- P2 shared Main User Entry browser baseline reuse: registered; KM004-specific
  validation is the lifecycle transition and current-revision Search behavior.
