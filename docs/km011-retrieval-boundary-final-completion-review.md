# KM011 Retrieval Boundary Runtime Review

## Scope

KM011 standardizes the retrieval boundary without replacing the existing
ingestion, graph, vector, lifecycle, or search frameworks.

## Canonical contract

| Entry mode | Canonical mode | Runtime source |
| --- | --- | --- |
| `basic`, `rag`, `vector` | `vector` | Qdrant RAG |
| `deep`, `graphrag` | `deep` | Neo4j GraphRAG |
| `hybrid` | `hybrid` | Qdrant + Neo4j |
| `auto` | `auto` | deterministic router |

`basic` remains an API-compatible name but no longer routes the unified
search path to the legacy Neo4j keyword implementation.

## Real-system validation

- FastAPI search API returned completed source-only tasks for all canonical
  modes and aliases.
- Real Qdrant point write/search returned the expected vector source.
- Real Neo4j entity/relation write/query returned the expected graph source.
- `basic` and `rag` returned canonical `vector` mode.
- `deep` and `graphrag` returned canonical `deep` mode.
- `hybrid` and `auto` remained distinct canonical routing contracts.
- Health and Version were both HTTP 200.
- Production and Production DB were untouched; write mode remained false.

## Status

- IMPLEMENTED: PASS
- INTEGRATED: PASS
- RUNTIME_VALIDATED: PASS
- USER_VISIBLE_VALIDATED: PASS via formal Search API source result entrypoint

The common Main User Entry browser baseline remains shared evidence; this
review validates only KM011-specific retrieval behavior.

## Technical debt

The disposable ingest smoke reached real embedding/store processing but the
host Ollama local generation exceeded the bounded window. This is a runtime
dependency timing issue and does not alter the retrieval boundary validation.
