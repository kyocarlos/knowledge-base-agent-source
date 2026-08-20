# WP1 Worker Failure/Restart Shadow Evidence

## Result

**PASS for isolated shadow recovery; not a production deployment claim.**

The drill started an isolated Docker Compose project, waited for the API health
endpoint, forcibly stopped `ingest_worker`, started that worker again, and
verified that it returned to `running`. The stack was removed with
`docker compose down --volumes --remove-orphans`.

## Evidence

- Date: 2026-08-20 Asia/Taipei
- Mode: `isolated-shadow`
- Image: `kb-wp01-e2e:20260820-cleanup-fix`
- Compose project: recorded in the JSON evidence
- Initial health: HTTP 200, `{"status":"healthy"}`
- Failure injection: `docker compose kill ingest_worker`
- Recovery: `docker compose up -d --no-build ingest_worker`
- Recovery assertion: `ingest_worker` state was `running`
- Cleanup assertion: no containers with the generated Compose project label remained
- Evidence SHA-256: `8b3d3460846d52ddd9ec8d782fc576e736886405a413984d62317558729f9817`

Full machine-readable evidence:
`outputs/worker-failure-recovery-shadow-20260820.json`

## Scope and limits

This validates worker process recovery in an isolated stack only. It does not
claim Redis reconnect/idempotency, backup/restore, production deployment,
formal E2E acceptance, or real instrument access. Those remain separate gates.
