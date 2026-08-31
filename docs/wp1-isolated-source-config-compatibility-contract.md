# WP1 Isolated Source and Config Compatibility Contract

The isolated Gate-B profile must use source files that are converged with the
approved candidate image contract. The cleanup authentication implementation
is sourced from the audited commit `7e563fcd3999a69447e1933a8d4185300eeeecb5`:
`src/test_reports/auth.py`, `src/test_reports/e2e_cleanup.py`, and
`src/web_api/e2e_cleanup_routes.py` are copied into the reviewed source
lineage as complete implementations, not compatibility shims.

The cleanup route remains disabled unless both the explicit E2E cleanup flag
and its protected identity mapping are present. Normal production
authentication is unchanged. Existing identity mappings are additive and are
not overwritten by isolated provisioning.

`config/config.yaml` is protected runtime configuration and is not committed
to Git. `scripts/provision_wp1_isolated_config.py` creates a fresh isolated
directory, copies only the required file with mode `0600`, and emits only
paths, SHA-256 values, modes, and contract status. The isolated directory is
temporary and must be removed during teardown. Missing or unreadable source
configuration is a pre-network fail-closed condition.

The helper accepts only `--execution-mode isolated` and rejects output paths
under the production checkout namespace. It does not provision production
configuration and does not perform Docker lifecycle operations.
