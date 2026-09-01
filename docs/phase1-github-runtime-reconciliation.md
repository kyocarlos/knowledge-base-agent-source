# Phase 1 GitHub Runtime Reconciliation

This package makes GitHub a verifiable release and status entry point. It does
not make GitHub a source of production secrets or production database data.

## Contracts

- `docs/phase1-status-manifest.json` is the reviewed declaration of the 18 P1
  roadmap work items and the approved application/runtime release identity.
- `scripts/validate_phase1_status.py` validates the declaration and rejects
  secret-like content.
- `scripts/collect_phase1_runtime_status.py` is read-only. It reads Git HEAD,
  Git cleanliness, bounded Health/Version responses and application container
  identity. It never reads container environments, mounts, database contents,
  credentials or private keys.
- The collector writes only sanitized JSON and explicitly records
  `production_touched=false` and `secrets_included=false` for its own action.

## GitHub workflow

`.github/workflows/phase1-runtime-status.yml` always validates the manifest in
GitHub Actions. The production snapshot job is disabled unless the repository
variable `KM_PRODUCTION_STATUS_ENABLED=true` is explicitly configured and a
self-hosted runner has the label `km-production-readonly`.

The self-hosted runner must have read-only operational permissions. It must not
have deployment credentials, database write credentials, or access to secret
values. It publishes `status/current.json` to the dedicated
`phase1-runtime-status` branch. A `PASS` snapshot requires all expected
identity and runtime checks to match; otherwise the snapshot is `MISMATCH` or
`STALE`.

## Deployment boundary

This is a status/reconciliation entry point, not a one-click production
deployment. A later deployment workflow may consume the reviewed manifest only
after separately adding image registry access, protected secret provisioning,
target preflight, data migration/restore policy, approval gates and rollback.
