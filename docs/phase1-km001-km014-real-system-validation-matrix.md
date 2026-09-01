# Phase 1 KM-001～KM-014 Real-System Validation Matrix

基線：`a84f3d287a654cc24f212dfd4e2ae070b958ad93`。本矩陣將 source 狀態與
真實系統結果分開；只有 `RUNTIME_VALIDATED`，或有使用者入口時再達到
`USER_VISIBLE_VALIDATED`，才能將該功能宣稱為完成。`IMPLEMENTED` 與
`INTEGRATED` 都不是 DONE。

`Runtime status` 使用 `NOT_YET_VALIDATED` 表示目前沒有該 KM 的真實驗證
結果；WP1 Production Acceptance evidence 不會被借用為 KM evidence。

| KM | Implementation status | Integration target | Real runtime target | User-visible entrypoint | Runtime validation method | Expected real-system result | Current runtime status | Evidence location |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| KM-001 | INTEGRATED (legacy chunk/index path only) | converter/chunker -> Qdrant + Neo4j | production-compatible stack with real document | `chat.html` search | upload/ingest a real versioned document; inspect processed output, chunk metadata, Qdrant point and Neo4j node | deterministic `document_id/document_version/chunk_id`, non-empty chunks and matching source metadata in both stores | NOT_YET_VALIDATED | new Batch A run evidence |
| KM-002 | INTEGRATED (report status exists; knowledge publish gate absent) | registry + Qdrant/Neo4j visibility filters | real registry and both stores | `chat.html` published search | create draft, mark ready, publish, search before/after and inspect superseded revision | draft invisible; published current revision searchable; prior revision superseded | NOT_YET_VALIDATED | new Batch A run evidence |
| KM-003 | INTEGRATED (delete-first re-ingest path exists) | re-ingest orchestration | disposable real stack first, then production-compatible stack | `chat.html` search | ingest v1, start v2 with injected store failure, query v1, then complete v2 and query current | v1 remains available after failed v2; pointer switches only after success | NOT_YET_VALIDATED | new Batch A run evidence |
| KM-004 | INTEGRATED (stores are called independently) | ingest registry + Neo4j + Qdrant | real Neo4j and Qdrant | API/search result | force one store failure and inspect API/result plus durable state; run success path | failure is visible and fail-closed; no PUBLISHED state on partial write; success yields retrieval | NOT_YET_VALIDATED | new Batch A run evidence |
| KM-005 | INTEGRATED (KM report workflow exists) | CSIT adapter boundary + WP1 upload/review/ingest | real CSIT-compatible API and KM runtime | CSIT Web / KM report API | submit through CSIT contract, approve in CSIT, observe KM indexing state | one approval source; KM does not invent a second business approval state | NOT_YET_VALIDATED | Batch B runtime evidence |
| KM-006 | INTEGRATED (GraphRAG writer exists) | entity/relationship writer | real Neo4j | `chat.html` GraphRAG mode | ingest document with two entities; Cypher query relationship and provenance | entity A -> relation -> entity B with document/chunk provenance | NOT_YET_VALIDATED | Batch B runtime evidence |
| KM-007 | IMPLEMENTED (metadata parsing paths exist) | `.source.json` -> ingest identity | real ingest worker and stores | report/search result metadata | ingest document with valid and malformed source metadata; inspect API/store result | valid metadata propagates; malformed metadata fails explicitly, never silently drops identity | NOT_YET_VALIDATED | Batch A/B runtime evidence |
| KM-008 | IMPLEMENTED (report graph path exists) | simple/report ingest -> report graph | real Neo4j and ingest worker | report/search result | ingest report-like simple document and query graph counts | no `NameError`; graph node counts and retrieval result are present | NOT_YET_VALIDATED | Batch B runtime evidence |
| KM-009 | INTEGRATED (global Entity name model exists) | Neo4j entity schema | real Neo4j | GraphRAG result | ingest same name in two namespaces and query both | same display name in different domains remains distinct | NOT_YET_VALIDATED | Batch B runtime evidence |
| KM-010 | INTEGRATED (entity fields currently overwritten) | Neo4j provenance relations | real Neo4j | GraphRAG citation/result | ingest two source documents mentioning one entity; query evidence | canonical entity retained with both source/chunk links; later ingest does not erase prior provenance | NOT_YET_VALIDATED | Batch B runtime evidence |
| KM-011 | INTEGRATED (multiple retrieval paths exist) | Qdrant RAG + Neo4j GraphRAG + hybrid router | real API and stores | `chat.html` | run one query per mode through the user entrypoint and inspect source type/citation | mode names, data source and citation are consistent with the contract | NOT_YET_VALIDATED | Batch C runtime evidence |
| KM-012 | IMPLEMENTED (URL resolver only; no first-class deployment contract) | Compose/service readiness + VectorStore | real Qdrant service or declared external Qdrant | API readiness/search | stop or isolate Qdrant, query readiness and ingest behavior, then restore and search | unavailable Qdrant makes readiness/ingest fail explicitly; no silent skip | NOT_YET_VALIDATED | Batch C runtime evidence |
| KM-013 | IMPLEMENTED (documentation currently drifts from code) | README/config/architecture contract | deployed source and runtime config | developer/user documentation | compare declared mode and endpoint with rendered Compose, API and real search | docs, config and runtime describe Qdrant/Neo4j consistently | NOT_YET_VALIDATED | Batch C review evidence |
| KM-014 | NOT_STARTED | separate TimescaleDB metric path | real TimescaleDB-compatible service | Portal metric query | write real metric rows keyed by `test_run_id`, query by time range and inspect citation | numeric time-series stored/queryable independently from report registry | NOT_YET_VALIDATED | future Batch C runtime evidence |

## Per-increment completion gate

For each independent increment:

1. Source implementation and focused tests pass.
2. Integration target is rendered and wired in the real runtime.
3. A real document/request reaches the actual container and database path.
4. The result is recorded as sanitized API/DB/search output or screenshot.
5. Health/Version remain `200/200`; Upload/Ingest/Search remain functional.
6. Affected WP1 paths are regression-checked before the next increment.

No raw credentials, resolved environment dumps or protected database values may
appear in evidence. Real-system validation may use a disposable integrated
stack, but a feature is not complete until it has also run once in an
approved production-compatible runtime.
