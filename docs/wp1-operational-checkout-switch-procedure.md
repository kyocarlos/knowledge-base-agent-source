# WP1 Operational Checkout Switch Procedure Review

## Status

- Scope: procedure only; not executed
- Production deployment: not run
- Container restart/recreate: not run
- Production write: not run

## Source Roots

- Old operational source root: `/home/da40_ai_gb10/knowledge-base`
- New operational source root: `/srv/knowledge-base-production-rebaseline-20260829-v3`
- New Git HEAD: `58d3080cbcf8d341b2f0a96c3ea7df8a1d82a29a`
- New GitHub branch: `wp1-production-operational-provenance-rebaseline-20260829`

The old checkout remains intact and is the rollback source for the checkout pointer only. It is not deleted, reset, cleaned, stashed, or rewritten.

## Protected External Overlay

The following target paths are outside Git and must be created/validated by the host owner before Phase A:

- `KB_RUNTIME_ENV_FILE=/home/da40_ai_gb10/.config/knowledge-base/runtime.env`
- `KB_CONFIG_ROOT=/home/da40_ai_gb10/.config/knowledge-base/config`
- `KB_DATA_ROOT=/home/da40_ai_gb10/knowledge-base/data`
- `KB_REPORT_ENV_FILE=/home/da40_ai_gb10/.config/knowledge-base/report-ingest.env`
- `KB_ROLLBACK_HELPER=/srv/knowledge-base-production-rebaseline-20260829-v3/scripts/rollback_pre_wp01.py`
- A2A protected env: `/home/da40_ai_gb10/.config/knowledge-base/km-a2a-bridge.env`

Required checks:

- protected env/config files exist, are readable by the owning service, and are mode `0600` where they contain secrets;
- no secret values are printed, committed, or included in evidence;
- `config/config.yaml` is not copied into Git;
- `KB_ROLLBACK_HELPER` exists, is absolute, executable, and has the approved SHA;
- all required overlay paths are recorded by path, owner, mode, and checksum only.

## Systemd Unit Change

Unit: `km-a2a-bridge.service`

Before:

- `WorkingDirectory=/home/da40_ai_gb10/knowledge-base`
- `EnvironmentFile=/home/da40_ai_gb10/knowledge-base/km_a2a_bridge/.env`

After, to be applied only in Phase A after approval:

- `WorkingDirectory=/srv/knowledge-base-production-rebaseline-20260829-v3`
- `EnvironmentFile=/home/da40_ai_gb10/.config/knowledge-base/km-a2a-bridge.env`

`ExecStart` must remain the reviewed A2A bridge command. No application code or bridge implementation is changed by this procedure.

## Phase A: Source/Config Alignment

1. Capture old unit file, old source root, old overlay paths, current Git HEAD, service state, and Docker container IDs.
2. Validate the new checkout HEAD, required tracked files, runner/crypto/nginx/restart SHA, and clean worktree.
3. Validate all protected overlay paths and the absolute rollback helper before changing the unit file.
4. Update only the operational pointer/source-root reference and the `km-a2a-bridge.service` path fields above.
5. Run `systemctl --user daemon-reload` only after the unit file and overlay validations pass.
6. Verify the loaded unit with `systemctl --user cat` and `systemctl --user show`; do not start or restart the service in Phase A.
7. Verify source-root, overlay, helper, Git HEAD, and file hashes read-only.
8. Compare Docker container IDs, image IDs, mounts, and service states with the pre-change snapshot. Any change is a fail-closed result.

Phase A does not invoke Docker Compose, `restart_kb.sh`, `--deploy`, `--deploy-pinned`, `up`, `restart`, or `recreate`.

## Phase B: Controlled Bridge Activation

Phase B is a separate change and requires a separate supervisor approval. If the bridge is not required for the WP1 acceptance path, leave it inactive and perform no restart.

If approved, restart only `km-a2a-bridge.service`; do not restart application containers or data services. Verify unit state, working directory, environment-file path, process command, and bridge health read-only.

## Switch Rollback

Rollback is triggered by any missing/unreadable overlay, helper mismatch, unexpected Git/worktree state, unit parse failure, unexpected container mutation, bridge activation failure, or health regression.

For Phase A rollback:

1. Restore the previous unit path values.
2. Run `systemctl --user daemon-reload`.
3. Do not restart the bridge unless Phase B had been separately approved and executed.
4. Re-run read-only unit/source/container checks.

For an approved Phase B failure, stop the bridge service, restore the prior unit, daemon-reload, and verify application containers/data services remain unchanged. No production deployment or data restore is part of this procedure.

## Post-Switch Read-only Checks

- `systemctl --user cat km-a2a-bridge.service` matches the approved paths;
- new checkout HEAD equals `58d3080cbcf8d341b2f0a96c3ea7df8a1d82a29a`;
- worktree is clean;
- runner, crypto, nginx, and restart hashes are exact;
- protected overlay paths, modes, and checksums pass without exposing values;
- checkpoint and rollback helper are readable/ executable;
- `docker ps` and `docker inspect` prove no container/image/mount change;
- baseline `/health`, `/api/v1/version`, Celery nodes, tasks, and queues remain unchanged;
- no production write, Redis/ledger mutation, migration, restore, or acceptance run occurred.

## Approval Boundary

This document requests review of the switch method only. It does not authorize Phase A execution, Phase B activation, application restart, production deployment, or synthetic acceptance.
