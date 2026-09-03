# Knowledge Base Architecture Contract

This is the canonical architecture description for the current application
lineage. README and operational documents should link here instead of
maintaining independent infrastructure claims.

## Runtime flow

```text
chat.html / Search API
        |
        v
FastAPI API shell
        |
        +--> Celery + Redis task execution
        |        |
        |        +--> MarkItDown / report converters
        |        +--> chunking and embedding
        |        +--> Qdrant vector write/search
        |        +--> Neo4j graph write/query
        |        +--> PostgreSQL report registry
        |
        +--> published/current visibility and source projection
```

## Retrieval contract

| Public mode | Backend | Meaning |
| --- | --- | --- |
| `basic`, `rag`, `vector` | Qdrant | vector RAG retrieval |
| `deep`, `graphrag` | Neo4j | graph retrieval |
| `hybrid` | Qdrant + Neo4j | combined retrieval |
| `auto` | router | selects the canonical mode |

The mode mapping is implemented by `src/retrieval_contract.py`. Qdrant is the
vector store; Neo4j is the graph store. Neo4j Vector and ChromaDB are not
current runtime dependencies.

## Required runtime dependencies

The Compose deployment declares Redis, PostgreSQL report registry, Neo4j and
Qdrant. Web and worker services receive an explicit `QDRANT_URL` and depend on
the Qdrant healthcheck. `KB_QDRANT_READINESS_REQUIRED=true` enables the strict
API readiness gate. If Qdrant is unavailable, readiness returns HTTP 503 and
vector writes fail closed.

The application may use an explicitly configured external Qdrant endpoint, but
an explicit `QDRANT_URL` is never silently replaced with another endpoint.

## Data boundaries

- Uploaded and staged files are stored under the configured upload/staging roots.
- PostgreSQL stores report submission and approval registry state.
- Qdrant stores vector points and source identity payloads.
- Neo4j stores graph nodes, relationships, and provenance.
- Redis stores task queue/result state.

Credentials, resolved environments, and private runtime values are deployment
configuration, not architecture documentation.
