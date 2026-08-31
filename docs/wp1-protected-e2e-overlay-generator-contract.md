# WP1 Protected E2E Overlay Generator Contract

`generate_e2e_runtime_env.py` is the versioned generator for the temporary
protected E2E Compose overlay. It receives an explicit `--execution-mode` and
requires a mode-matching authoritative Run ID; it never infers mode from an
untrusted prefix.

Production accepts only `TR-E2E-WP1-PROD-*`. Isolated Gate-B accepts only
`TR-E2E-WP1-GATEB-ISOLATED-*`. An isolated output cannot be placed in a
production evidence namespace or production path.

The input is a protected hash-only JSON object containing exactly the three
approved E2E roles and a non-empty `token_sha256` value for each role. The
output contains only the six approved `KB_E2E_*` variables, is written with
mode `0600`, and must not overwrite an existing file. Raw tokens, passwords,
private keys, and hash source contents are never printed or written to normal
evidence. Regular identity mappings are not emitted or replaced; Compose
merges the temporary E2E mappings additively.

The generator does not start, stop, recreate, build, pull, or inspect a
container. Lifecycle execution remains the responsibility of the reviewed
orchestrator and its `--no-build` Compose procedure.
