# KM ↔ CSIT Integration v1 canonical contract adoption — 2026-10-14

**Status: READY FOR CLEAN LIVE E2E.** KM DEV source, CI, migration, API and stopped worker image are aligned. Integration remains disabled, and no new Live E2E has been executed. This is not an Integration v1 completion or Production acceptance claim.

## Contract and source

- Canonical authority: [CSIT-System commit `3a9ae52f04625aeee5fd01e7a3565f5972fc9122`](https://github.com/pattymou/CSIT-System/tree/3a9ae52f04625aeee5fd01e7a3565f5972fc9122/contracts/csit-km-integration-v1), path `contracts/csit-km-integration-v1/`.
- KM source branch: `codex/km-dev-handoff-20261014`; approved code commit: [`45108b1fb4a4672945d99238080f75069929f2ec`](https://github.com/kyocarlos/knowledge-base-agent-source/commit/45108b1fb4a4672945d99238080f75069929f2ec). Baseline: `b3aa002556c7905e3d91691420dbcdc7b7f19ba1`.
- The four vendored schema files match the exact pinned upstream bytes and SHA-256 values in `UPSTREAM.json`. The CI sync script downloads only that commit; it never follows `main` or `latest`.
- `src/csit_integration_v1/` and the vendored schemas are CURRENT CSIT INTEGRATION V1. The old `config/csit_km_v1_contract.json`, `src/csit/`, `tests/test_csit_*.py`, and manifest workflow remain LEGACY MANIFEST CONTRACT. Legacy behavior was not changed.

## Contract fixes

- `eventId`, `documentId`, and project/case/task IDs use Pydantic UUID types and serialize as JSON UUID strings. Reference `number` and `name` are required but nullable; empty strings are accepted by the wire model. `Document.sizeBytes` requires at least 1. Filename/path/MIME safety validation remains in place.
- Six internal lineage columns (`*_code`, `*_name`) now allow SQL NULL via `20261014_csit_integration_v1_nullable_lineage.sql`. The wire property stays `number`, never `code`. Repository tests prove NULL persists in lineage and `request_payload`.
- Repository outbox and tests use one production `build_callback_payload` function. Processing uses `updatedAt` + transition `startedAt`; Completed uses `updatedAt` + `completedAt`; Failed uses `updatedAt` + real `last_error_at` as `failedAt`, with nonblank error fields enforced by the production callback builder against the exact vendored schema before outbox insertion. Four tests reject blank or whitespace Failed error fields.
- Default service principal claim is `principal_type=service`; client registration, credentials, scopes, audience, token endpoint and Shared Identity were not changed.

## Verification

- Full isolated CSIT v1, Human OIDC, Binding and related KM regression suite: **265 passed**, 1 non-blocking test-client deprecation warning. The packaged offline verifier also passed.
- [GitHub push CI run `38527129749`](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/38527129749): **success** on code commit `45108b1...`.
- API and worker images built from that commit with `org.opencontainers.image.revision=45108b1...`. Both images passed the canonical offline verifier with `--network none`.
- The running DEV API container itself ran `python -m src.csit_integration_v1.offline_verify --require-disabled`: **PASS** for ingestion and all three callback schemas. Ten deployed source/schema files match the code checkout SHA-256 values. This verifies actual deployed code, not only unit tests.

## KM DEV runtime and data

| Component | Actual state |
|---|---|
| API container | `137abd9c24cbb5635084a8d4bcc05e0e285099ca4c4eea67645d8933291fccf71`; running/healthy; image `sha256:64c88c2b463a798034a6e18ff45d9665cfcd48cdc7da65ec270d480f9aa6df33` |
| Worker container | `6f02a948ec07505c4daeb90048544b74d3195711839712b8feb62c88be4217a91`; created/OFF; image `sha256:d9613774ed05764314f2cce85f370fe1b3e34f4c30688d892ed15d2bddcb2c58f` |
| API health | `status=ok`, `integrationEnabled=false`; `KM_CSIT_ENABLED=false` |
| Metadata DB | `km_control`, `public`; six lineage columns nullable after migration |
| Jobs/callbacks | Unchanged: 1 Completed job; 1 Delivered and 3 historical Failed callback delivery rows |

The live Compose image references now point to `v1-canonical-45108b1`. A protected override, pre-deployment Compose backup, image/container snapshots, CI/test logs, DB before/after counts, and rollback instructions are retained under `/home/da40_ai_gb10/.km-control/csit-canonical-20261014/` (mode 0700; files mode 0600). Previous API/worker images are retained; `compose-rollback-builder-gate.yml` restores the prior `bbc6039` image pair, and the original pre-canonical rollback remains available. DB migration is additive; image rollback can leave nullable columns in place.

## Clean Live E2E boundary

No inbound ingestion, document download, new job, worker processing, callback delivery, or Human OIDC live login was performed in this adoption. The existing Completed job was not resumed or replayed. A future controlled Live E2E should enable the approved DEV integration and single worker, use a new canonical UUID producer event, and verify Processing/Completed/Failed callbacks against CSIT plus graph/numeric outcomes as applicable. Prior historical callback failure rows remain evidence, not proof of current runtime failure.
