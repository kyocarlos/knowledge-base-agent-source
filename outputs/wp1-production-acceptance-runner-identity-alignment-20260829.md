# WP1 Production Acceptance Runner Identity Alignment

**Result:** `PASS_WITH_VERSIONED_RUNNER_AND_DOCUMENTED_REVISION_DELTA`  
**Production touched:** false

## Auditable identity chain

| Item | Identity |
| --- | --- |
| Crypto review commit | `920b9ac3aa85f2ac2933256db7adf8207ff3b2ec` |
| Crypto helper | `scripts/websocket_crypto_preflight.py` |
| Crypto SHA-256 | `eabed02c15d4234e99188e572616aa2132446b19e5a96b186427ac39d926501b` |
| Versioned runner | `scripts/run_wp1_production_acceptance.py` |
| Runner introduction | `714e5a33ee33c4a3b0da7423a6460cd4dc7a1d46` |
| Current runner revision | `ae7f78cff4efd0c08bec7aab434b1ca13b48e6d7` |
| Current runner SHA-256 | `5f9be73c25148c035644f5d1ca78d5b95ed86e20aca637b4f03df1c8b15b3cd8` |

The runner imports the reviewed helper directly. It contains no production-only signing implementation.

## Controls and validation

- Before network/write activity, Git HEAD, runner SHA, crypto SHA, candidate source/release/image/timestamp, run-ID uniqueness, fixture manifest, attachment checksum, multipart headers, idempotency scope, and cleanup scope are checked. Any mismatch fails closed.
- Exact-candidate isolated execution run `TR-E2E-WP1-PROD-RUNNER-ISOLATED-20260829-000447-db53535e` passed metadata attribution, Search, Upload 202, Duplicate, Self-read 200, Approve 200, Ingest completed, cleanup, post-cleanup 404, and residual 0.
- The same execution recorded the required WebSocket chronology: challenge, Ed25519 local sign/verify, signed `req.connect`, `res(id=c1,ok=true)`, `chat.send`, final event, and close code 1000.
- The exact-candidate stack was disposable and cleaned. No production endpoint, data, credentials, or runtime was used.

## Revision delta

The full isolated execution used runner SHA `0b9f12...`. The follow-up runner SHA `5f9be...` changes only failure-path evidence persistence: a runtime-probe failure after the pre-network gate now writes sanitized evidence before returning fail-closed. It does not alter the success-path request, crypto, WebSocket, Upload, Ingest, or Cleanup contract.

The current exact-head runner passed the 10 focused runner/crypto tests and an exact-HEAD pre-network probe, including Git/runner/crypto SHA equality and fail-closed behavior. This delta is explicit so the execution and source identities are not conflated.

## Decision

Submit this evidence for `WP1 Production Acceptance Runner Identity Alignment Review`. Production retry remains unauthorized until that review passes.
