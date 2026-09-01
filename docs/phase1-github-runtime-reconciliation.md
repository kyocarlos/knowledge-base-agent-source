# Phase 1 GitHub Runtime Reconciliation

This package makes GitHub a verifiable release and status entry point. It does
not make GitHub a source of production secrets or production database data.

## Contracts

- `docs/phase1-status-manifest.json` is the reviewed declaration of the 18 P1
  roadmap work items, the last accepted release, and the currently deployed
  runtime identity.
- `accepted_release` records the last production-accepted candidate and its
  historical acceptance run. It is evidence of acceptance, not a claim about
  what is deployed now.
- `deployed_release` records the runtime identity expected to be deployed now.
  After WP1 acceptance the application services intentionally restore to the
  production baseline, so this identity is declared separately.
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
`STALE`. The comparison is against `deployed_release`, not the historical
`accepted_release`. For a `BASELINE` deployment this means service status,
service image identity and Health/Version availability. Unavailable Git or
release metadata remains non-blocking provenance debt. For a `RELEASE`
deployment, the collector also compares the approved application and
operational identities. Differences are reported, never repaired by changing
Production.

## Deployment boundary

This is a status/reconciliation entry point, not a one-click production
deployment. A later deployment workflow may consume the reviewed manifest only
after separately adding image registry access, protected secret provisioning,
target preflight, data migration/restore policy, approval gates and rollback.
