# WP1 Production Tooling Safe Sync Plan Review

## Status

**Plan only; production alignment has not been performed.**

Canonical `agent/km-plan-v2.6-anderson` is now at `07c36e123a92dc1b2774f99c647eddf504d673e2`, including the approved PR #23 tooling. The real checkout remains at `59dd8bf...` with existing dirty changes.

## Protection of Dirty Checkout

The real checkout contains unrelated local changes, and `restart_kb.sh` itself has a pre-existing `5` added / `1` deleted diff with SHA-256 `d58b975c6bc5b978c62503428157d34ae6467945ac8680d0c33d6db774a9d0fc`. No reset, clean, stash, forced checkout, branch overwrite, or file overwrite has been performed.

## Deterministic Sync Method

1. Record a timestamped backup and SHA-256 of the current dirty `restart_kb.sh`.
2. Review its three-way diff against canonical and abort on conflict or unrelated-change loss.
3. Apply the canonical script by a three-way patch, preserving any explicitly approved local change; abort on unresolved conflict.
4. Add only the five missing canonical tooling/test files.
5. Run shell syntax, Python compilation, deterministic tests, diff checks, and `restart_kb.sh --help`.
6. Verify canonical hashes and prove all unrelated dirty files remain unchanged.

The sync is not authorized in this record. Production deployment and restart remain prohibited until this plan is approved and all post-sync checks pass.
