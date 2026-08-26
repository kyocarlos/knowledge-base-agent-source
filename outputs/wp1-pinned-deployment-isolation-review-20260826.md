# WP1 Pinned Deployment Isolation / Rollback Path Review

## Scope

The pinned deployment orchestration was corrected and validated in isolated dry-run. No production service, dependency service, working-tree file, database, Redis/ledger state, stuck task, or synthetic data was changed.

## Corrections

- Pinned recreate now uses `--no-deps --no-build --pull never --force-recreate`.
- Only `web`, `celery_search_worker`, `celery_ingest_worker`, and `celery_beat` are passed to the recreate command.
- The approved release tag and exact image ID remain unchanged.
- Rollback uses an explicit absolute helper path and checks file existence plus executability before any recreate.
- Missing/invalid rollback helper fails closed before container mutation.
- The bounded readiness checker remains after recreate and before acceptance gates.

## Validation

- Valid pinned deployment dry-run: PASS.
- Invalid rollback helper: non-zero exit before recreate, PASS.
- Dependency services are not selected or started by the pinned recreate command: PASS.
- Existing `kb-neo4j` name conflict path is avoided by `--no-deps`: PASS by deterministic command inspection.
- `bash -n restart_kb.sh`: PASS.
- Readiness/Compose tests: `5 passed`.
- No production/container/working-tree mutation: PASS.

Machine-readable evidence: `outputs/wp1-pinned-deployment-isolation-review-20260826.json`.

## Decision

`PASS` for isolated pinned deployment isolation and rollback-path validation. Production deployment remains prohibited until this review is accepted.
