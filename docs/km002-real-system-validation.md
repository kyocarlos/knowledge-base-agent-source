# KM002 Real-System Validation

KM002 implements the versioned knowledge lifecycle:

`draft -> ready -> published -> superseded`

The existing ingestion registry is extended with a durable
`knowledge_revisions` table. Ingested package points remain in Qdrant and
revision nodes remain in Neo4j; publish changes visibility metadata instead of
deleting the prior revision first.

## Runtime contract

- New package revisions are registered as `draft`.
- Default vector and report-graph search accepts `published` and
  `is_current=true` only. Legacy records without lifecycle fields remain
  readable.
- `ready` is the only state that can be published.
- Publishing updates Qdrant and Neo4j before advancing the durable registry.
  Store failure leaves the registry and previous current revision unchanged.
- Revision identity in Neo4j uses `package_id`, so document versions coexist.

The runtime endpoints are:

- `POST /api/v1/knowledge/revisions`
- `GET /api/v1/knowledge/revisions/{package_id}`
- `POST /api/v1/knowledge/revisions/{package_id}/transition`

These endpoints are intended for the integrated application runtime and are
not enabled or exercised against Production by this change.

## Disposable real-runtime result

Validation used a fresh Docker Compose project with real Redis, Celery Search,
Qdrant, Neo4j and the FastAPI application. A real versioned document produced
Qdrant vectors and Neo4j revision nodes. The Search API was called after each
transition.

| Scenario | Result |
| --- | --- |
| draft is absent from default Search | PASS |
| v1 publish makes the revision searchable | PASS |
| v2 publish makes v2 current and hides v1 superseded revision | PASS |
| injected v3 store failure leaves v3 ready and v2 searchable | PASS |

Sanitized result:

```json
{"draft_invisible":true,"v1_published":true,"v2_current":true,"v1_superseded":true,"failed_v3_preserved_ready":true,"real_runtime":true}
```

No Production service, database, filesystem or acceptance run was modified.
