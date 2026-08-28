# WP1 WebSocket-Fix Production Acceptance Failure

- Result: `FAIL_CLOSED`
- Failure gate: `WEBSOCKET_RUNNER_ED25519_SIGNING_ERROR`
- Production Gate: `NO-GO`
- Run ID: `TR-E2E-WP1-PROD-WS-FINAL-20260828-092526-f09a31f0`

Pinned deployment, readiness, Health, Search, Upload, duplicate, self-read, approve, and Ingest all passed. The runner failed before any WebSocket protocol action because its Python signing call supplied RSA-only arguments to an Ed25519 private key. No WebSocket auth frame, `connect`, or `chat.send` was sent after this error. This is a runner/test-harness failure and is not evidence of candidate application regression.

The synthetic submission was cleaned successfully with residual `0`. Approved rollback completed successfully to the persistent checkpoint and restored baseline Health, Celery 2 nodes, and empty tasks/queues. No stuck task was retried, and no manual Redis/ledger mutation, migration, restore, WP2 work, real instrument access, or secret evidence occurred.

The correction is isolated to the temporary runner: Ed25519 signing must use `private_key.sign(payload)`; RSA padding/hash arguments are invalid. Production retry is prohibited until isolated validation and a new supervisor GO review.
