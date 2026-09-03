# KM012 Qdrant First-Class Dependency Runtime Review

## Scope

KM012 makes Qdrant a declared deployment dependency. The application receives an explicit `QDRANT_URL`, Compose waits for Qdrant health, `/api/v1/health/ready` reports dependency failure, and vector writes fail closed instead of silently skipping the store.

## Implementation

- `docker-compose.yml` declares `qdrant`, persistent storage, `/healthz` healthcheck, and healthy dependencies for web and workers.
- `app/api/v1/router.py` performs the opt-in strict readiness check and returns sanitized HTTP 503 when Qdrant is unavailable.
- `src/runtime_config.py` preserves an explicitly configured Qdrant URL and never falls back to another endpoint.
- `src/vector_store/__init__.py` records initialization failure and exposes `ensure_available()`; vector writes now fail closed.
- `src/ingest.py` checks Qdrant availability before writing vectors or registering the revision.

## Validation

Focused contract tests: `4 passed`.

Real disposable runtime evidence: [`km012-qdrant-readiness-runtime-20260903.json`](evidence/km012-qdrant-readiness-runtime-20260903.json).

- Running Qdrant: health 200, application readiness 200.
- Stopped Qdrant: application readiness 503.
- Stopped Qdrant vector write gate: explicit fail-closed error.
- Restarted Qdrant: health 200, application readiness 200.
- Disposable containers after teardown: 0.
- Production and production database touched: false.
- Secrets included: false.

## Status

`IMPLEMENTED = PASS`

`INTEGRATED = PASS`

`RUNTIME_VALIDATED = PASS`

`USER_VISIBLE_VALIDATED = PASS` through the real readiness API, which exposes the KM012-specific dependency behavior.

The host Docker BuildKit activity directory was read-only, so no new application image was built. Validation used an existing compatible application image with this branch source mounted read-only; rebuilding the candidate image remains a release gate before any deployment authorization. Production deployment/write was not performed.
