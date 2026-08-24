# WP0 Candidate Production Preflight Refresh

## Result

`NO-GO` due to current-runtime configuration drift. This was a read-only preflight; no production service was restarted and no production data was changed.

## Candidate

- Source: `2ef93d6b47d05b1acbc05fadc0df8393fefd41a0`
- Release: `wp0-e2e-auth-metadata-fix-20260824-r1`
- Image: `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`
- Build timestamp: `2026-08-24T16:18:21+08:00`
- Local candidate image and capability gate: PASS

## Current Runtime

- Application image: `sha256:8f009d19a8bfec29736cfb08b1175795aaabdc44449bf298e29d5c8974ed129c`
- Nginx image: `sha256:c4ebb06c9c9db8551ac0f15d3b7b37589c7cbc04e78cbfb4ac33bd57193db776`
- Health, WP0/WP1 gates, Celery and queues: PASS; Celery has 2 nodes and queues are empty.
- `/api/v1/version`: HTTP 200, but current legacy runtime reports `commit`, `release_id`, `image_digest` and `build_timestamp` as null. This is recorded as an observation, not a candidate pass.
- Current frontend mount: `/home/da40_ai_gb10/knowledge-base/.frontend-build-runtime-user8:/usr/share/nginx/html:ro`
- Persistent frontend: `index.html` and `chat.html` present, 17 files, 13 assets, manifest `e0d4fff65bde65df72da2afec6131d1cf46cba2d38c5e275cc2c9393186cc255`.

## Checkpoint and Drift

- Checkpoint: `/home/da40_ai_gb10/knowledge-base/outputs/current-runtime-checkpoints/current-runtime-frontend-20260824-153723`
- Checkpoint verification: PASS
- Checkpoint SHA256SUMS SHA-256: `dfc4432a677cd749a5f902a21c17dea94dd505374efef227d77926d64b219267`
- Checkpoint application image equals current application image: PASS
- Checkpoint frontend mount was `/tmp/kb-metadata-validation-fix/.frontend-build-runtime-user8`
- Current frontend mount is the persistent path above
- Therefore `production_drift=true` and rollback readiness for this deployment is `BLOCKED_BY_DRIFT`.

The current checkpoint cannot be used as the final deployment rollback baseline until a new current-runtime checkpoint is explicitly authorized and created. No checkpoint was created in this read-only step.

## Proposed Compose

Using the candidate branch Compose with the scheduler profile and an ephemeral image override, render validation passed for `web`, `celery_search_worker`, `celery_ingest_worker` and `celery_beat`:

- all four resolved to the exact candidate digest;
- all four received identical release metadata;
- shared ledger path was `/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3`;
- persistent frontend path remained the proposed source;
- candidate image capability validation passed.

The actual deployment must use `docker compose ... --no-build` with the digest-pinned override. The base `build:` context must not be allowed to replace the candidate.

## Evidence

Machine-readable details are in `production-preflight-refresh.json`. Secrets were not included. Production remains untouched and the Production Gate remains `NO-GO` pending a fresh current-runtime checkpoint that matches the current frontend mount configuration.
