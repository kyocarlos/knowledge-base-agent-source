# WP1 Metadata Validation Fix Candidate r2

## Scope

This is an isolated validation record for Draft PR #16. Production was not deployed, restarted, or written. PR #15 remains unchanged.

## Root Cause

The generator produced valid RFC3339 (`2026-08-24T06:47:20+08:00`). The temporary production Compose override used an unquoted YAML mapping scalar, which was rendered as `2026-08-24 06:47:20 +0800 CST`. The application rejected that rendered value. The legal `+08:00` offset was not the failure.

The contract now requires RFC3339 with `T` and an explicit `Z` or `+/-HH:MM` timezone. Generator, startup validation, `/api/v1/version`, and rendered-Compose preflight share this contract.

## CI Portability Correction

The first exact-head CI runs failed because the GitHub runner's newer Compose rejected the unsafe YAML timestamp during schema validation, while the local Compose version rendered a coerced value that the deployment validator rejected. Both are secure outcomes. The regression test now accepts either explicit rejection path and never accepts the unsafe value.

## Candidate

- Source: `703075efe862736cffe5159edfcb3b1940c5ae09`
- Release: `wp1-metadata-validation-fix-20260824-r2`
- Image: `sha256:8f009d19a8bfec29736cfb08b1175795aaabdc44449bf298e29d5c8974ed129c`
- Build timestamp: `2026-08-24T10:09:35+08:00`
- Registry push: not performed

## Isolated Validation

- Focused metadata/Compose tests: 19 passed
- Four Uvicorn workers: PASS; four startup completions; no `database is locked`
- `/api/v1/version`: exact source/release/image/timestamp PASS
- Synthetic run: `TR-E2E-WP1-METADATA-FIX-R2-20260824-101128-1dc2c3bc`
- Health, Search, report self-read, Upload/Ingest, dedup, worker completion, report approve/read: PASS
- Worker recovery, in-flight redelivery, application idempotency, Redis reconnect/SETNX: PASS
- Cleanup dry-run/apply: PASS
- Active tasks after cleanup: 0
- Synthetic residuals: 0
- Post-cleanup Health: PASS

The first r2 harness attempt stopped before ingest because a regenerated attachment did not match the XLSX manifest hash. The isolated stack was removed, the approved synthetic attachment was restored, and the fresh rerun passed.

## Gate

- Production Gate: **NO-GO**
- Production touched: false
- Secrets included: false
- WP2 changed: false
- Ready for Production Preflight Review: pending final exact-head WP0/WP1 CI rerun
