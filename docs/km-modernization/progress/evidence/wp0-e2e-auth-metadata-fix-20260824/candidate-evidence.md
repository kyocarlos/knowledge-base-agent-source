# WP0 E2E Auth + Runtime Metadata Candidate

## Result

**Isolated candidate validation: PASS**. Production remains **NO-GO**.

- Source: `2ef93d6b47d05b1acbc05fadc0df8393fefd41a0`
- Release: `wp0-e2e-auth-metadata-fix-20260824-r1`
- Image: `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`
- Build timestamp: `2026-08-24T16:18:21+08:00`

## Fix A

The candidate image contains `authenticate_report_agent`, `authenticate_report_reviewer`, the scoped E2E identities, and report routes. Regular authentication remains separate and fail-closed.

## Fix B

The exact metadata tuple was injected into an isolated runtime and `/api/v1/version` returned all four non-null values matching the candidate identity.

## Isolated Smoke

Four services started. Health, Search, E2E agent health, upload, duplicate submission, report review, ingest completion, cleanup dry-run/apply and residual count `0` passed.

Host pytest was unavailable; `py_compile`, deterministic capability assertions, image probe and isolated smoke passed.

No production deployment, restart, migration, business write, or real instrument operation was performed.
