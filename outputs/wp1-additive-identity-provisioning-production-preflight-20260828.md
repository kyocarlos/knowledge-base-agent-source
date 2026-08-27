# WP1 Additive Identity Provisioning Production Preflight

## Result

`PASS_READ_ONLY_PREFLIGHT`. No production deploy, restart, write, retry, Redis/ledger mutation, migration, restore, WP2 work, or real instrument access was performed.

## Current Runtime

- Project: `knowledge-base`
- Application image: `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`
- Nginx image: `sha256:c4ebb06c9c9db8551ac0f15d3b7b37589c7cbc04e78cbfb4ac33bd57193db776`
- Network: `knowledge-base_default`
- Health: HTTP `200`
- `/api/v1/version`: HTTP `200`; baseline metadata remains the known legacy `null` observation and is not treated as candidate identity.
- Celery: `2` nodes; active/reserved/scheduled `0`; queues `0`
- Frontend mount: `/home/da40_ai_gb10/knowledge-base/.frontend-build-runtime-user8` to `/usr/share/nginx/html`, read-only
- Nginx dynamic resolver: active, Docker DNS `127.0.0.11`, variable-based `web` upstream

## Checkpoint and Candidate

Checkpoint verification and rollback readiness both pass; `production_drift=false`, and the checkpoint application image matches current production.

Candidate remains unchanged:

- Source: `914d7c829269779f13c47d71ebd27ecb9dde84ec`
- Release: `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Tag: `kb-wp1-release:wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Image: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`
- Build timestamp: `2026-08-26T15:21:36+08:00`
- Pinned dry-run: `PASS`

The dry-run confirmed `pull_policy=never`, `--no-deps`, `--no-build`, `--force-recreate`, application-services-only scope, exact metadata, shared ledger path, and no mutation.

## Additive Identity Plan

The next production write must use the same isolated-validated runner and a new production run ID. Before network/write, it must verify both temporary mappings are present: the E2E Upload/Search mapping and the additive `KB_AGENT_TOKEN_HASHES_JSON` self-read mapping. Existing mappings remain preserved. Removal is deterministic, must be performed regardless of acceptance result, and must verify fail-closed authentication afterward. No credential material is included in evidence.

## Recommendation

All read-only preflight gates pass. Submit this package for supervisor `Production GO Review`; do not perform production retry without a new explicit GO.
