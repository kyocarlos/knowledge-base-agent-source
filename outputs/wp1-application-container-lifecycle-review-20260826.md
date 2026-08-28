# WP1 Application Container Lifecycle Alignment Review

## Read-only diagnosis

Production uses Compose project `knowledge-base`, network `knowledge-base_default`, and fixed container names `kb-web`, `kb-celery-search`, `kb-celery-ingest`, and `kb-celery-beat`. The prior isolated invocation set `COMPOSE_PROJECT_NAME=kb`; Compose therefore did not align with the existing project identity while the fixed names remained global. This caused the `kb-celery-beat` name conflict before candidate startup.

## Deterministic replacement procedure

- Pin project identity to `knowledge-base`.
- Validate all four existing application names, Compose project/service labels, and expected network before mutation.
- Validate the absolute executable rollback helper and checkpoint before mutation.
- Recreate only `web`, `celery_search_worker`, `celery_ingest_worker`, and `celery_beat` with `--no-deps --no-build --pull never --force-recreate`.
- Do not create, start, or recreate Neo4j, Redis, PostgreSQL, Qdrant, nginx, or any other dependency/data service.
- Keep the approved release tag and exact image ID; no rebuild or dynamic tag is permitted.
- Run bounded readiness after recreate and before acceptance gates.

Missing rollback helper validation exits before any recreate. The valid dry-run rendered the correct project, exact pinned image, and four-service mutation contract without changing containers or the working tree.

## Results

- Read-only container identity/mount inspection: PASS.
- Valid pinned lifecycle dry-run: PASS.
- Invalid rollback helper fail-closed before mutation: PASS.
- Shell syntax and deterministic lifecycle contract: PASS.
- Regression tests: `5 passed`.
- Production mutation: none.

Machine-readable evidence: `outputs/wp1-application-container-lifecycle-review-20260826.json`.

## Decision

`PASS` for isolated application container lifecycle alignment and rollback-path validation. Production deployment remains prohibited until this review is accepted.
