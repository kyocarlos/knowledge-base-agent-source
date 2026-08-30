# WP1 Production Transaction Orchestrator Contract

`scripts/wp1_production_transaction_orchestrator.sh` is the only shell
orchestrator for the approved one-run transaction. It does not generate a Run
ID and rejects an absent or malformed `WP1_RUN_ID`; the operator must provide
the already approved fresh ID. It invokes the versioned maintenance entrypoint,
never the runner directly.

The script has no `set -e`; every mutation and restoration return code is
checked explicitly. `EXIT`, `INT`, `TERM`, and `HUP` all converge on one
idempotent restoration path. Restoration recreates only `kb-web` with
`--no-build --no-deps --force-recreate`, using the baseline env and pinned
override. If no mutation started, the exit handler records that restoration was
not required and performs no service action.

The temporary overlay must be mode `0600`, contain only the six approved web
E2E variable names, and remain outside the evidence root. Its contents are
never printed or copied to evidence. The script records only event names,
timestamps, booleans, exit classes, and sanitized result files.

Enablement is accepted only when `kb-web` has write mode and its six variables,
`celery_ingest_worker` has the five non-write-mode identity/cleanup variables,
and search/beat have no `KB_E2E_*` variables. Baseline requires write mode
`false` or absent before mutation.

The authoritative result is `FAIL_CLOSED` for a non-zero runner, signal,
exception, incomplete evidence, or restoration failure. Cleanup or restoration
cannot change an acceptance failure to `PASS`. This is an orchestration
contract, not a security authorization boundary: environment markers remain
accidental-path guards and do not prevent deliberate caller forgery.

Production activation is not authorized by this file alone. It requires the
separate supervisor GO and isolated validation of this script.

The same versioned script supports two explicit execution profiles. The default
`production` profile uses the approved operational Compose file, fixed
production inspect targets, and the production base URL; it rejects isolated
profile inputs. The `isolated` profile requires an explicit Compose project,
Compose file, base URL, inspect targets, container prefix, non-production port
set, and non-production data/config/ledger roots. It adds the project name to
every Compose invocation and uses the configured inspect targets and base URL.
Isolated roots, ports, container names, and project names must not collide with
production. The Compose profile is responsible for binding those roots and
ports; the orchestrator records `execution_mode` in every orchestration event.
