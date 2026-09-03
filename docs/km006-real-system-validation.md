# KM006 Real-System Validation

## Scope

KM006 defines the Neo4j graph relationship contract used by the existing
ingestion and GraphRAG writers. It keeps endpoint identity separate from
display names and carries source provenance on each relationship.

## Implementation status

| Layer | Status | Evidence |
|---|---|---|
| IMPLEMENTED | PASS | `src/graph_relationship_contract.py`, Neo4j writers and schema |
| INTEGRATED | PASS | `src/ingest.py`, `src/extract_entities.py`, `src/graphrag/__init__.py` |
| RUNTIME_VALIDATED | PASS | `docs/evidence/km006-real-runtime-20260903.json` |
| USER_VISIBLE_VALIDATED | PASS | `docs/evidence/km006-http-search-runtime-20260903.json` |

## Real runtime result

The disposable Neo4j runtime used the application writer and schema setup with
real Neo4j, not a mock. It verified:

- `entity_key` uniqueness constraint is present.
- Three entities, including duplicate display names in separate namespaces,
  are stored without endpoint collision.
- One `RELATES_TO` relationship is written using endpoint keys.
- Re-running the same document does not duplicate the relationship.
- Graph query returns the relationship and its source document, source chunk,
  evidence type and review status.
- The application `SearchEngine.deep_search()` path returns the graph result
  with the same relationship provenance from the real Neo4j runtime.
- Document cleanup matches both the KM006 `source_document` field and the
  legacy `source` field.

## Boundary

The shared Main User Entry baseline remains the common browser baseline. The
formal HTTP `POST /search` path was exercised through FastAPI, Celery and
Redis against real Neo4j. The completed task returned graph sources containing
the KM006 relationship provenance. No production deployment or production
database mutation was performed.
