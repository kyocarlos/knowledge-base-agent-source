# WP1 Metadata Validation Fix Evidence

## Root cause

Retry 4 failed because the temporary deployment override expressed the build timestamp as an unquoted YAML mapping scalar. Compose interpreted the RFC3339 source value `2026-08-24T06:47:20+08:00` as a YAML timestamp and rendered it as `2026-08-24 06:47:20 +0800 CST`. The application correctly rejected that rendered non-RFC3339 value.

The legal `+08:00` timezone was not the failure. The original evidence remains unchanged; this record adds the distinction between generated and rendered values.

Earlier CI and isolated validation injected metadata directly through environment variables. They therefore validated the original value but did not inspect the final Compose-rendered value.

## Contract and fix

- Build timestamps require RFC3339 with `T` and an explicit `Z` or `+/-HH:MM` timezone.
- Source commit, release ID, image digest, and build timestamp use one shared validation module.
- The runtime env generator and application startup use that shared contract.
- `restart_kb.sh` now inspects rendered Compose JSON before changing services.
- Web, search worker, ingest worker, and beat must receive values exactly equal to the approved release identity.
- Empty or `unknown` timestamp remains `null` only for development compatibility; a release runtime requires all four identity fields.
- Lease and business logic were not changed.

The previously coerced value is rejected during preflight. Canonical Compose rendering using the generated mode `0600` env file passes.

## Candidate

- Source: `e67bd9b0dbfdcc316d94d3e2b1ae590a1ba06efe`
- Release: `wp1-metadata-validation-fix-20260824-r1`
- Image: `sha256:510a2ad488085ab49968d361e20014ee939fdaef2dc32453dad9f13f28482588`
- Build timestamp: `2026-08-24T09:55:14+08:00`
- Registry push: pending separate approval

## Validation

- Metadata/API contract: 26 passed.
- Real Docker Compose rendering: 2 passed, including YAML coercion rejection.
- Four-worker Uvicorn startup: 4 started, 4 application startup complete, no `database is locked`.
- `/health` and `/api/v1/version`: PASS with exact source/release/image/timestamp identity.
- Shared ledger path and file identity across web/search/ingest/beat: PASS.
- Search, report self-read, upload/ingest, duplicate dedup, register/claim/completion, approve/read: PASS.
- Worker recovery, in-flight redelivery, application idempotency, Redis reconnect/SETNX: PASS.
- Cleanup dry-run/apply: PASS; active task count 0; residual count 0; post-cleanup Health PASS.
- Synthetic run: `TR-E2E-WP1-METADATA-FIX-20260824-095900-unique`.

The containerized full repository run produced 123 passed, 2 skipped, and one legacy report-route registration failure. The same single failure was reproduced on the unmodified PR #15 base in the same environment, so it is not attributed to this fix. GitHub exact-head WP0/WP1 CI remains the formal repository gate.

Two earlier harness attempts are retained in the audit record: one transient Neo4j dependency startup failure, and one fixture/run-ID mismatch caused by reusing an older XLSX. Both isolated stacks were removed; the fresh matching fixture completed the full validation.

## Safety and gate

Production was not deployed, restarted, or written. No migration, restore, WP2 work, real-instrument access, or credential material occurred.

`Production Gate = NO-GO`. This candidate is ready for supervisor Production Preflight Review, not for production retry.
