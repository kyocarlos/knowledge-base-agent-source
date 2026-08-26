# WP1 Ingress Failure Evidence Preservation Review

## Result

Isolated contract validation: **PASS**.

This change adds a best-effort, read-only capture immediately after bounded deployment readiness fails and before the approved rollback path. Capture failure is intentionally non-fatal and cannot prevent rollback.

## Captured Evidence Scope

- Candidate `kb-web` and `kb-nginx` container IDs, IPs, and networks.
- Docker DNS resolution for `web` from the nginx container.
- nginx-to-web `/health` and `/api/v1/version` probes.
- Formal ingress `/health` and `/api/v1/version` response headers/bodies.
- Redacted nginx access/error logs and effective `nginx -T` configuration.
- Readiness evidence path, timestamps, and attempts.

## Safety Properties

- `capture_before_rollback=true` in the pinned deployment failure path.
- Capture operations are read-only and best-effort.
- Every capture failure is tolerated; rollback remains the next deployment action.
- No container stop/restart/remove/compose mutation or Git operation occurs in capture.
- Authorization, Cookie, password, token, secret, and API-key values are redacted from captured logs/configuration.
- No production retry, synthetic write, stuck-task mutation, migration, restore, or real-instrument action was performed.

## Isolated Validation

- `bash -n restart_kb.sh`: PASS
- Contract, readiness, and Compose tests: **8 passed**
- `git diff --check`: PASS
- Production runtime capture: not run by authorization boundary.

The machine-readable record is `outputs/wp1-ingress-failure-evidence-preservation-review-20260826.json`.
