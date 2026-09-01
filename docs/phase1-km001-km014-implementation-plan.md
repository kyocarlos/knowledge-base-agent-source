# Phase 1 KM-001～KM-014 Implementation Plan

## Baseline and policy

- Application implementation branch starts from `a84f3d287a654cc24f212dfd4e2ae070b958ad93`.
- Governance `main` remains the manifest/reconciliation reference and is not
  the application feature baseline.
- Protected WP1 runtime functions remain regression-protected.
- Strategy: `REUSE -> EXTEND -> INTEGRATE`; no rewrite without a separate
  reviewed exception.

## Batch A — KM-001～KM-004: Knowledge / RAG Core

| KM | Exact scope | Reused components | Completion evidence | Risk |
| --- | --- | --- | --- | --- |
| KM-001 | Package schema, revision identity, deterministic chunk metadata, source metadata propagated to both stores | `src/chunker`, `src/vector_store`, Neo4j document writer | contract tests and package smoke | P0 |
| KM-002 | Publish state machine and current revision filter | existing registry/search/store APIs | draft invisible, publish visible, supersede old revision | P0 |
| KM-003 | Draft-first re-ingest and pointer switch | existing `ingest_document`/`reingest` flow | injected failure preserves prior published revision | P0 |
| KM-004 | Store readiness/transaction outcome | existing Qdrant and Neo4j adapters | either-store failure returns failure and cannot publish | P0 |

Batch A does not include destructive legacy migration, full ontology redesign,
TimescaleDB, CSIT workflow replacement or Portal redesign.

## Batch B — KM-005～KM-010: CSIT / API / Graph Integration

1. Make CSIT the business source of truth for report approval and publication;
   KM owns validation/indexing status only.
2. Preserve the existing WP1 `Upload -> Review -> Ingest` input contract and
   add CSIT adapters rather than a second report ingestion path.
3. Correct graph relationship source/target semantics, metadata parsing and
   simple report graph statistics.
4. Introduce domain-scoped entity identity and additive provenance links.

Batch B starts only after Batch A's focused functional validation and review.

## Batch C — KM-011～KM-014: Governance / Portal / Time-series

1. Publish one retrieval mode contract: Qdrant RAG, Neo4j GraphRAG, hybrid
   Qdrant plus Neo4j evidence, and explicit routing.
2. Make Qdrant a configurable first-class dependency with readiness checks;
   do not silently fall back to an undeclared host service.
3. Align README, architecture docs, API mode names and deployment contract.
4. Add a separate TimescaleDB metrics path keyed by `test_run_id` and time
   range; do not use report workflow PostgreSQL as a substitute.

## Review gates

Each batch must provide source commit/PR, changed files, focused tests, compile
or static validation, functional smoke evidence and unresolved P1/P2 list.
Production deployment remains unauthorized until a separately reviewed
candidate is available. A P0 data/security/rollback regression stops the batch;
P2 documentation or observability debt is recorded without blocking core
functionality.
