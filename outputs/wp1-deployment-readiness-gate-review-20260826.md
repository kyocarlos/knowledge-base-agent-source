# WP1 Production Readiness Wiring Review

## Scope

Isolated/non-production validation of the production rollout caller. No production deployment, synthetic write, stuck-task retry, Redis/ledger mutation, migration, restore, or WP2 work was performed.

## Accepted wiring

- `restart_kb.sh` `run_deploy` calls `scripts/check_deployment_readiness.py` after service recreation and before `run_acceptance_gates`.
- Direct backend URL is `KB_DIRECT_BACKEND_URL`, defaulting to `http://127.0.0.1:8000`.
- Formal ingress URL is `KB_INTERNAL_BASE_URL`, defaulting to `https://127.0.0.1:${KB_HTTPS_PORT:-3030}`.
- Timeout is `KB_RESTART_WAIT_TIMEOUT_SECONDS`, default `120` seconds; retry interval is `2` seconds.
- Commit, release ID, image digest, and build timestamp are forwarded as expected metadata when configured.
- Readiness requires both direct and ingress `/health` and `/api/v1/version` to return valid responses and exact metadata.
- A non-zero checker exit makes the deployment fail closed and invokes rollback; acceptance gates are after readiness only.
- The legacy `wait_for_http_200` helper is not used in the formal `run_deploy` path. It remains for generic status/restart acceptance and is not a substitute for deployment readiness.

## Isolated results

- Delayed-start bounded readiness test: PASS.
- Attempt count and first-success timestamps recorded: PASS.
- Unavailable endpoints returned checker exit `1` and result `FAIL`: fail-closed assertion PASS.
- Compose/metadata/readiness tests: `5 passed`.
- `bash -n restart_kb.sh`: PASS.
- Caller static contract: PASS.

Machine-readable evidence: `outputs/wp1-deployment-readiness-gate-review-20260826.json`.

## Decision

`PASS` for readiness wiring in isolated validation. This evidence does not authorize or claim a production deployment. A future production attempt must use this checker and stop on any non-zero result.
