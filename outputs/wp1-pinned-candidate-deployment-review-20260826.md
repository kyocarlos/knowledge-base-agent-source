# WP1 Pinned Candidate Deployment Review

## Scope

The pinned deployment mode was validated in isolated dry-run only. No production container, working-tree file, database, Redis/ledger state, stuck task, or synthetic data was changed.

## Candidate hard gates

- Release tag: `kb-wp1-release:wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Exact image ID: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`
- Source: `914d7c829269779f13c47d71ebd27ecb9dde84ec`
- Release: `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Build timestamp: `2026-08-26T15:21:36+08:00`

The caller validates the tag with `docker image inspect`, requires the exact image ID, generates a metadata-safe override with `pull_policy: never`, and requires a verified checkpoint. It does not rebuild, derive identity from checkout HEAD, create a dynamic deployment tag, or perform Git reset/checkout/clean/stash.

## Dry-run results

- `restart_kb.sh --deploy-pinned --dry-run`: PASS.
- Compose configuration and shared ledger validation: PASS.
- Four services render the exact release tag, `pull_policy: never`, exact metadata, and shared ledger path: PASS.
- Checkpoint checksum verification: PASS.
- No container/image/working-tree mutation: PASS.
- Readiness and Compose tests: `5 passed`.
- Shell syntax and caller contract: PASS.

The non-dry-run path recreates only the four application services, calls `scripts/check_deployment_readiness.py`, and only then calls acceptance gates; a readiness failure invokes rollback and exits non-zero.

Machine-readable evidence: `outputs/wp1-pinned-candidate-deployment-review-20260826.json`.

## Decision

`PASS` for isolated pinned-candidate deployment validation. Production deployment remains pending a separate approved execution after this review.
