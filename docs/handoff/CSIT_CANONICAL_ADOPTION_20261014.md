# KM ↔ CSIT Integration v1 canonical contract adoption — 2026-10-14

**Status: READY FOR CLEAN LIVE E2E.** KM DEV source, CI, migration, API and stopped worker image are aligned. Integration remains disabled, and no new Live E2E has been executed. This is not an Integration v1 completion or Production acceptance claim.

## Contract and source

- Canonical authority: [CSIT-System commit `3a9ae52f04625aeee5fd01e7a3565f5972fc9122`](https://github.com/pattymou/CSIT-System/tree/3a9ae52f04625aeee5fd01e7a3565f5972fc9122/contracts/csit-km-integration-v1), path `contracts/csit-km-integration-v1/`.
- KM source branch: `codex/km-dev-handoff-20261014`; approved code commit: [`bbc6039a142a8359fe7a3361deb7e715e12092f2`](https://github.com/kyocarlos/knowledge-base-agent-source/commit/bbc6039a142a8359fe7a3361deb7e715e12092f2). Baseline: `b3aa002556c7905e3d91691420dbcdc7b7f19ba1`.
- The four vendored schema files match the exact pinned upstream bytes and SHA-256 values in `UPSTREAM.json`. The CI sync script downloads only that commit; it never follows `main` or `latest`.
- `src/csit_integration_v1/` and the vendored schemas are CURRENT CSIT INTEGRATION V1. The old `config/csit_km_v1_contract.json`, `src/csit/`, `tests/test_csit_*.py`, and manifest workflow remain LEGACY MANIFEST CONTRACT. Legacy behavior was not changed.

## Contract fixes

- `eventId`, `documentId`, and project/case/task IDs use Pydantic UUID types and serialize as JSON UUID strings. Reference `number` and `name` are required but nullable; empty strings are accepted by the wire model. `Document.sizeBytes` requires at least 1. Filename/path/MIME safety validation remains in place.
- Six internal lineage columns (`*_code`, `*_name`) now allow SQL NULL via `20261014_csit_integration_v1_nullable_lineage.sql`. The wire property stays `number`, never `code`. Repository tests prove NULL persists in lineage and `request_payload`.
- Repository outbox and tests use one production `build_callback_payload` function. Processing uses `updatedAt` + transition `startedAt`; Completed uses `updatedAt` + `completedAt`; Failed uses `updatedAt` + real `last_error_at` as `failedAt`, with nonblank error fields enforced by canonical schema tests.
- Default service principal claim is `principal_type=service`; client registration, credentials, scopes, audience, token endpoint and Shared Identity were not changed.

## Verification

- Full isolated CSIT v1, Human OIDC, Binding and related KM regression suite: **261 passed**, 1 non-blocking test-client deprecation warning. The packaged offline verifier also passed.
- [GitHub push CI run `38524774749`](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/38524774749): **success** on code commit `bbc6039a...`.
- API and worker images built from that commit with `org.opencontainers.image.revision=bbc6039a...`. Both images passed the canonical offline verifier with `--network none`.
- The running DEV API container itself ran `python -m src.csit_integration_v1.offline_verify --require-disabled`: **PASS** for ingestion and all three callback schemas. Ten deployed source/schema files match the code checkout SHA-256 values. This verifies actual deployed code, not only unit tests.

## KM DEV runtime and data

| Component | Actual state |
|---|---|
| API container | `fb635e28c242f58a14b49cad058e99878df4ced57c3f8745c2fd4a3d4859c68e`; running/healthy; image `sha256:1555da50b77c7609cb82d9d8246c2a029689deabae677227698105fb5c001d84` |
| Worker container | `ce7f0d85564a6fa3ff960ed210df1fb53c250388808c9f16468e9075feef8230`; created/OFF; image `sha256:57157596cc082146e0c30730ae65d7edf99d264afe054a4f1c30bd1255aa05d9` |
| API health | `status=ok`, `integrationEnabled=false`; `KM_CSIT_ENABLED=false` |
| Metadata DB | `km_control`, `public`; six lineage columns nullable after migration |
| Jobs/callbacks | Unchanged: 1 Completed job; 1 Delivered and 3 historical Failed callback delivery rows |

The live Compose image references now point to `v1-canonical-bbc6039`. A protected override, pre-deployment Compose backup, image/container snapshots, CI/test logs, DB before/after counts, and rollback instructions are retained under `/home/da40_ai_gb10/.km-control/csit-canonical-20261014/` (mode 0700; files mode 0600). Previous API/worker images are retained. DB migration is additive; image rollback can leave nullable columns in place.

## Clean Live E2E boundary

No inbound ingestion, document download, new job, worker processing, callback delivery, or Human OIDC live login was performed in this adoption. The existing Completed job was not resumed or replayed. A future controlled Live E2E should enable the approved DEV integration and single worker, use a new canonical UUID producer event, and verify Processing/Completed/Failed callbacks against CSIT plus graph/numeric outcomes as applicable. Prior historical callback failure rows remain evidence, not proof of current runtime failure.
