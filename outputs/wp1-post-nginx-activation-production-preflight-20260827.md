# WP1 Post-Nginx-Activation Production Preflight Revalidation

Result: **PASS (read-only)**

- Current application image: `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`
- Current nginx config SHA-256: `7696757b4800ec6b8778e17a4fc9222aee2c90242a87a0a7b57b4d18f2e86e93`
- Persistent frontend mount: `/home/da40_ai_gb10/knowledge-base/.frontend-build-runtime-user8` -> `/usr/share/nginx/html` (read-only)
- Formal `/health`: HTTP 200
- Formal `/api/v1/version`: HTTP 200
- WP0/WP1 runtime gates: PASS
- Celery: 2 nodes; active/reserved/scheduled and queues empty
- Checkpoint verification: PASS
- Rollback readiness: PASS
- Rollback target matches current runtime: `true`
- Production drift: `false`

## Approved Candidate

- Source: `914d7c829269779f13c47d71ebd27ecb9dde84ec`
- Release: `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Tag: `kb-wp1-release:wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Image ID: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`
- Build timestamp: `2026-08-26T15:21:36+08:00`
- Exact image pin/local availability: PASS
- Compose metadata/shared ledger validation: PASS

## Pinned Dry-run

`restart_kb.sh --deploy-pinned --dry-run` passed with `pull_policy: never`, `--no-deps`, `--no-build`, and `--force-recreate` contract validation. No container, image, worktree, Redis, ledger, or production data mutation occurred.

The current `/api/v1/version` is the existing rollback baseline and returns HTTP 200 with null release metadata; the approved candidate was not deployed in this read-only preflight.
