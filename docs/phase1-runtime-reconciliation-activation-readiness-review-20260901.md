# Phase 1 Runtime Reconciliation Activation Readiness Review

**Decision: HOLD**

This review covers the minimum safety boundary before enabling the production
self-hosted status collector. It does not authorize deployment, database
access, credential provisioning, or `KM_PRODUCTION_STATUS_ENABLED=true`.

## Current execution identity

- Current shell account: `da40_ai_gb10` (uid `1000`).
- No separate `github-runner`, `runner`, or dedicated KM read-only account was
  present in the local passwd inventory.
- This shell is not accepted as proof of a dedicated production runner
  identity.

## Negative verification

All checks were performed without reading secret contents and without
attempting Compose mutation:

| Check | Result | Meaning |
|---|---|---|
| `/srv/.../.git` write probe | `DENIED` | Current sandbox blocks the write |
| Production config write probe | `DENIED` | Current sandbox blocks the write |
| Production data write probe | `DENIED` | Current sandbox blocks the write |
| `docker exec kb-web true` | `ALLOWED` | Fails the required Docker restriction |
| Docker inspect/socket access | `ALLOWED` | Collector account has Docker access |
| Known protected env readability | `ALLOWED` | Fails secret isolation for this account |
| `docker compose up/down/restart` | `NOT_ATTEMPTED` | No mutation was attempted |
| Production file touch | `NOT_ATTEMPTED` | No mutation was attempted |

The denied filesystem probes are environment evidence only; they do not prove
that an eventual self-hosted runner account has the same restrictions. The
allowed Docker and protected-file checks are sufficient to keep activation on
hold for the current account.

## Required infrastructure remediation before activation

1. Provision a dedicated runner OS account, separate from Production service
   accounts and operators.
2. Place the runner workspace outside Production data and config roots.
3. Remove Docker socket access from the runner, or provide a narrowly scoped
   read-only status broker that cannot execute `exec`, Compose mutation, or
   volume operations.
4. Ensure the runner cannot read Production env files, token/password files,
   private keys, or resolved container environments.
5. Re-run the negative checks as the dedicated account and preserve only
   sanitized PASS/DENIED results.
6. Keep `KM_PRODUCTION_STATUS_ENABLED` unset or `false` until the above
   checks pass and receive separate supervisor approval.

## Result

`PRODUCTION RUNTIME RECONCILIATION ACTIVATION = HOLD`.

No Production service, database, filesystem data, or configuration was
modified by this review.
