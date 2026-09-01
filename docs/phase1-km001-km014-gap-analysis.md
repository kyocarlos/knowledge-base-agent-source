# Phase 1 KM-001～KM-014 Gap Analysis

基線：`a84f3d287a654cc24f212dfd4e2ae070b958ad93`（WP1 Production Core
Runtime Acceptance approved application lineage）。本文件只描述 source
狀態；「程式碼存在」不等於功能完成。Production、資料庫與現有 runtime
均未因本盤點修改。

## Status definitions

- `EXISTING`：已有可重用實作，且本項主要 contract 已覆蓋。
- `PARTIAL`：已有入口或部分能力，但仍缺正式 contract、整合或安全條件。
- `MISSING`：canonical source 沒有可用實作。
- `RUNTIME_VALIDATED`：已有可追溯 runtime evidence 證明核心流程；不代表
  架構 backlog 全部完成。

## Matrix

| KM | v2.6 requirement | Phase 1 WP | Existing source / API / storage | Tests / evidence | Status | Missing / reusable / dependency | Risk | Order |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KM-001 | Knowledge Package v1 | P1-WP12, P1-WP13, P1-WP14 | `src/chunker`, `src/vector_store`, `src/ingest`, Neo4j `Document`/`SourceChunk`, Qdrant payload | chunk/vector/ingest tests; no formal package schema evidence | `PARTIAL` | Add shared version/chunk/content/source contract; reuse chunker and stores; prerequisite for KM-002～004 | P0 | 1 |
| KM-002 | Draft/Published/Superseded lifecycle | P1-WP10, P1-WP12, P1-WP13 | `src/test_reports/registry.py`, report routes, Qdrant search, Neo4j graph | report upload/review tests; no published-only knowledge gate | `PARTIAL` | Add publish state and current revision pointer; reuse registry and search filters; depends KM-001 | P0 | 2 |
| KM-003 | Non-destructive re-ingest/version switch | P1-WP12, P1-WP13, P1-WP14 | `src/reingest.py`, `cleanup_existing_document()` in `src/ingest.py` | re-ingest code exists; no failure-injection preservation proof | `PARTIAL` | Replace delete-first path with draft-first switch; reuse ingest pipeline; depends KM-001/002 | P0 | 3 |
| KM-004 | Neo4j/Qdrant consistency transaction | P1-WP13, P1-WP14, P1-WP18 | `src/ingest.py`, `src/vector_store`, Neo4j writer | some report failure checks; no cross-store transaction state | `PARTIAL` | Durable DRAFT/READY/PARTIAL_FAILED state and fail-closed publish; depends KM-001～003 | P0 | 4 |
| KM-005 | CSIT/KM boundary and approval ownership | P1-WP04, P1-WP05, P1-WP06, P1-WP10 | report routes, `src/test_reports/registry.py`, PostgreSQL registry | WP1 report acceptance tests | `PARTIAL` | Move business approval source-of-truth to CSIT; KM keeps validation/indexing state; reuse upload/ingest APIs | P0 | Batch B |
| KM-006 | Graph relationship source semantics | P1-WP14 | `src/graphrag/__init__.py`, `src/ingest.py`, Neo4j | basic graph tests; provenance semantics incomplete | `PARTIAL` | Separate source/target entity from document/chunk provenance; reuse GraphRAG writer | P0 | Batch B |
| KM-007 | Reliable source metadata parsing | P1-WP12, P1-WP14 | `src/ingest.py`, `.source.json` reader | metadata paths covered indirectly | `PARTIAL` | Module-level parsing and fail-closed validation; reuse metadata files | P0 | Batch A/B boundary |
| KM-008 | Simple report graph stats correctness | P1-WP10, P1-WP14 | simple/report paths in `src/ingest.py`, `src/report_graph.py` | report route tests; simple path needs direct proof | `PARTIAL` | Capture graph writer result and test report-like simple ingest; reuse report graph | P0 | Batch B |
| KM-009 | Domain-scoped Entity identity | P1-WP14 | `src/graphrag/neo4j_schema.py`, ingest entity MERGE | graph schema tests; global name constraint remains | `PARTIAL` | Add canonical identity/namespace without breaking existing labels; depends KM-006 | P1 | Batch B |
| KM-010 | Multi-source entity provenance | P1-WP14 | Neo4j entity writer and relationship writer | no multi-source provenance acceptance | `PARTIAL` | Preserve evidence relationships instead of overwriting entity fields; depends KM-006/009 | P1 | Batch B |
| KM-011 | RAG/GraphRAG/Hybrid mode contract | P1-WP17, P1-WP18 | `src/search`, `src/graphrag`, `src/main.py`, Portal/API | search tests and WP1 runtime evidence | `PARTIAL` | Declare Qdrant RAG, Neo4j GraphRAG, hybrid composition and citations; reuse paths | P1 | Batch C |
| KM-012 | Qdrant first-class deployment/readiness | P1-WP03, P1-WP13 | `src/vector_store`, `src/runtime_config.py`; no Compose Qdrant service | no deployment readiness contract | `MISSING` | Add configurable Qdrant dependency/readiness without hardcoding host; depends KM-001 and deployment review | P1 | Batch C |
| KM-013 | Architecture/document consistency | P1-WP01, P1-WP17 | README, config docs, search/vector modules | no architecture consistency check | `PARTIAL` | Align documentation with Qdrant/Neo4j implementation; reuse canonical contracts | P1 | Batch C |
| KM-014 | TimescaleDB time-series ingestion/query | P1-WP15 | no Timescale connector or schema; report registry is PostgreSQL workflow storage | no time-series evidence | `MISSING` | Add separate metric storage/reference contract; must not overload report registry | P2 | Batch C |

## Batch A scope: KM-001～KM-004

Batch A is the first implementation slice and is intentionally limited to the
knowledge path:

`Document -> Processing -> Index -> Search -> Knowledge retrieval`

It will reuse the existing converter/chunker, embedding model, Qdrant client,
Neo4j writer and search entry points. It will not rewrite the WP1 upload,
duplicate, self-read, approve, ingest, WebSocket or cleanup workflow. The exact
implementation boundary is:

1. shared package metadata and deterministic revision-scoped chunk identity;
2. published/current visibility as a reusable search predicate;
3. draft-first ingest and a durable publish transition;
4. fail-closed result when either index store cannot reach READY;
5. failure-injection tests proving the previously published revision remains
   queryable when a new revision fails.

No legacy production data migration, reindex, destructive cleanup or Production
deployment is authorized by this document.

## Dependency and review order

`KM-001 -> KM-002 -> KM-003 -> KM-004 -> KM-005/KM-006/KM-007/KM-008 ->
KM-009/KM-010 -> KM-011/KM-012/KM-013 -> KM-014`

The order is implementation guidance, not a claim that later items are done.
Every item requires a fresh source scan before modification and a focused
validation record after modification.
