# KM014 TimescaleDB Time-Series Runtime Review

## Scope

KM014 adds a separate numeric time-series path for long-test metrics. It does
not overload the PostgreSQL report registry or the Neo4j report graph.

## Implementation

- `timescale/timescaledb:2.17.2-pg16` is declared as an independent Compose service with persistent storage and healthcheck.
- `TIMESCALEDB_URL` and `TIMESCALEDB_PASSWORD` are explicit deployment configuration.
- `src/timeseries_store.py` owns the independent `km_timeseries_metrics` schema, idempotent metric write, and `test_run_id` plus time-range query.
- `app/api/v1/timeseries.py` exposes sanitized `POST /api/v1/metrics` and `GET /api/v1/metrics/{test_run_id}` responses.
- Existing report upload/review/ingest, Qdrant, Neo4j, and registry paths are unchanged.

## Real-system validation

Focused contract tests: `2 passed`.

Using real FastAPI and TimescaleDB containers, the runtime wrote two metrics
for `KM014-REAL-20260903` and queried both through the formal API with a
bounded time range. Both responses were HTTP 200 and returned the expected
metric values plus package/document identity. The table existed only in the
dedicated time-series database; the report registry was not modified.

Health API returned HTTP 200. Disposable containers were removed after the
test. Production and production database were untouched, and no secrets were
included in evidence.

## Status

`IMPLEMENTED = PASS`

`INTEGRATED = PASS`

`RUNTIME_VALIDATED = PASS`

`USER_VISIBLE_VALIDATED = PASS` through the formal metrics API, which is the
KM014-specific user-visible entrypoint.

The first request during database startup returned HTTP 503 and succeeded on
retry after the service healthcheck passed. A future UI/Portal presentation
can reuse this API; it is outside KM014's minimal scope.
