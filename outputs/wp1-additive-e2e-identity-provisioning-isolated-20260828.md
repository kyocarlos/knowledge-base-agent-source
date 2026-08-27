# WP1 Additive E2E Identity Provisioning Isolated Validation

## Result

`PASS` in isolated/non-production validation. `production_touched=false`; no production deployment, write, migration, restore, or real instrument access occurred.

## Candidate

- Source: `914d7c829269779f13c47d71ebd27ecb9dde84ec`
- Release: `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1`
- Image: `sha256:54650d64a2867be1ee21bbcb47951d5bc28d85ef76fcac370310b36a9c80bee3`
- Build timestamp: `2026-08-26T15:21:36+08:00`
- Services: `web`, `search_worker`, `ingest_worker`, `beat`

## Full Additive Flow

Run ID: `TR-E2E-WP1-PROD-IDENTITY-ISOLATED-20260827-160753-004f1c73`

The exact candidate isolated runner passed Upload `202`, approve `200`, report self-read `200`, duplicate submission with `duplicate=true`, ingest terminal state `completed`, worker completion, cleanup dry-run/apply, post-cleanup lookup `404`, WebSocket handshake/response/close code `1000`, and residual count `0`. The isolated Compose stack was removed after the run.

The run ID date contains `20260827` because of the isolated runtime clock. This is retained as an audit note and is not rewritten.

## Additive Auth Matrix

The matrix used a synthetic temporary identity and a separate redacted existing regular identity. Credential values and hashes were not recorded.

| Provisioning state | Upload auth | Self-read auth | Existing regular mapping |
|---|---:|---:|---:|
| E2E mapping only | PASS | `403 FAIL_CLOSED` | Preserved |
| E2E + regular self-read mapping | PASS | PASS | Preserved |
| Both temporary mappings removed | `403 FAIL_CLOSED` | `403 FAIL_CLOSED` | Preserved |

This demonstrates that the two mappings must be provisioned together for the temporary identity. Removing them is additive-safe and leaves the existing regular mapping intact; repeated removal remains non-destructive.

## Safety and Limits

- `secrets_included=false`
- `production_touched=false`
- Synthetic residual count: `0`
- No application code or candidate image was modified.
- The partial matrix is an auth-contract probe; endpoint-level full-flow results are supplied by the exact candidate isolated runner.

## Recommendation

The isolated additive provisioning contract is ready for supervisor review. Production retry remains unauthorized until a separate Production Preflight and Production GO approval.
