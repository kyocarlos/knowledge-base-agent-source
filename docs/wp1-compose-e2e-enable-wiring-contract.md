# WP1 Compose E2E Enablement Wiring Contract

This contract is configuration-only. Protected credential values and token hashes are supplied at runtime and are never committed here.

## Service Scope

- `web` / `kb-web` receives all six explicit E2E variables.
- `celery_ingest_worker` receives only the identity and cleanup variables required by the reviewed isolated contract.
- `celery_search_worker` and `celery_beat` receive no E2E variables.
- `KB_E2E_WRITE_MODE_ENABLED` is scoped to `kb-web` and defaults to `false`.

## Variables

- `KB_E2E_WRITE_MODE_ENABLED`
- `KB_E2E_AGENT_TOKEN_HASHES_JSON`
- `KB_E2E_REVIEWER_TOKEN_HASHES_JSON`
- `KB_E2E_CLEANUP_ENABLED`
- `KB_E2E_CLEANUP_TOKEN_HASHES_JSON`
- `KB_E2E_CLEANUP_TEST_RUN_ID_PREFIX`

All values use Compose interpolation. Secret material is provided only by the protected runtime environment. Missing values resolve to disabled/empty defaults and must not enable E2E writes.

## Activation Boundary

This change does not activate production write mode. A separately authorized transaction must verify rendered Compose configuration, effective `kb-web` environment, additive mappings, and baseline restoration to `false`. Only `kb-web` may be recreated for that transaction; no other service is implied by this contract.
