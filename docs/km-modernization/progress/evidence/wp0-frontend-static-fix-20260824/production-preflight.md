# WP0 Frontend Static Production Preflight

Date: 2026-08-24

## Result

`Production Gate = NO-GO`

This was read-only. No production restart, deploy, copy, write, migration, restore, or real-instrument operation was performed.

## Current Runtime

- nginx container: `kb-nginx`, image `sha256:c4ebb06c9c9db8551ac0f15d3b7b37589c7cbc04e78cbfb4ac33bd57193db776`
- application image: `sha256:8f009d19a8bfec29736cfb08b1175795aaabdc44449bf298e29d5c8974ed129c`
- `/health`: HTTP 200
- `/api/v1/version`: HTTP 200; commit `703075efe862736cffe5159edfcb3b1940c5ae09`
- WP0/WP1 runtime gates: PASS
- Celery: 2 nodes; active/reserved/scheduled and queues empty

## Current Static Mount: FAIL

The live nginx mount is:

`/tmp/kb-metadata-validation-fix/.frontend-build-runtime-user8 -> /usr/share/nginx/html:ro`

The source exists but contains 0 files. `index.html`, `chat.html`, asset count, and nginx static readability therefore fail. This reproduces the supervisor-reported production frontend blocker.

## Proposed Static Mount: PASS

The PR #19 contract proposes:

`KB_FRONTEND_BUILD_DIR=/home/da40_ai_gb10/knowledge-base/.frontend-build-runtime-user8`

The path is persistent and non-temporary. Read-only validation found:

- `index.html`: PASS
- `chat.html`: PASS
- file count: 17
- asset count: 15
- manifest: PASS
- manifest SHA-256: `54b0e47f6f4afbcb6999df511aba2f0ae82d1f324849dc992a017e48db338e06`
- owner: `1000:1000`
- directory mode: `0775`
- files readable: PASS
- rendered target: `/usr/share/nginx/html`
- nginx root: `/usr/share/nginx/html`, consistent with target

## Rollback Boundary

The approved checkpoint is verified, but its application image is `sha256:a3220ec...`, while current production is `sha256:8f009d19...`. Therefore production drift is true and the old checkpoint cannot be used as the current rollback baseline for a new deployment. A new current-runtime checkpoint must be created in an approved maintenance window before deployment. The PR script has a fail-closed frontend restore path, but the paired current frontend rollback snapshot is still pending.

## Decision

The static candidate itself passes the hard gate, but production preflight remains `NO-GO` because the live mount is still empty and rollback baseline drift must be reconciled. Do not modify W34, PPTX, or WP0 94% state.
