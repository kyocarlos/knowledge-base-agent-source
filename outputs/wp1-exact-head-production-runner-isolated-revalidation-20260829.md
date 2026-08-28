# WP1 Exact-HEAD Production Runner Isolated Success Revalidation

**Result:** `PASS`  
**Run ID:** `TR-E2E-WP1-PROD-RUNNER-ISOLATED-20260829-002434-ae228a7e`  
**Production touched:** false

## Exact runner identity

- Git HEAD: `04ab05526ee00ac1e62788bf61d22470c2b463ad`
- Runner: `scripts/run_wp1_production_acceptance.py`
- Runner SHA-256: `5f9be73c25148c035644f5d1ca78d5b95ed86e20aca637b4f03df1c8b15b3cd8`
- Shared crypto helper: `scripts/websocket_crypto_preflight.py`
- Crypto SHA-256: `eabed02c15d4234e99188e572616aa2132446b19e5a96b186427ac39d926501b`

The pre-network gate passed exact Git HEAD, runner SHA, crypto SHA, candidate identity, fresh run-ID uniqueness, fixture manifest, multipart attachment, idempotency, and cleanup scope checks.

## Exact candidate result

The disposable Compose stack ran candidate `914d7c829269779f13c47d71ebd27ecb9dde84ec` / `wp1-deployment-metadata-yaml-quoting-fix-20260826-r1` / `sha256:54650d64...` with matching four-service metadata.

Search passed. Upload returned 202 with a submission ID; duplicate detection passed; self-read and approval returned 200; ingest reached `completed`. The versioned runner then completed the WebSocket sequence: challenge, signed connect, `res(id=c1,ok=true)`, `chat.send`, final event, and normal close code 1000.

Cleanup dry-run/apply passed, post-cleanup lookup returned 404, and residual count was zero. Disposable containers and data were removed. No production endpoint, runtime, data, secret material, or real instrument was used.
