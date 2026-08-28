# WP1 Final Controlled-Retry Production Acceptance Review

## Decision

Production acceptance was stopped fail-closed at the WebSocket application protocol gate. Rollback passed. Production Gate remains `NO-GO`.

## Passed Before Failure

The new unique run ID passed the read-only uniqueness gate and full fixture/multipart contract. The additive identity contract and protected runtime secret gate passed. Pinned deployment and bounded readiness passed with the approved candidate. Health, Search, agent health, Upload `202`, duplicate detection, self-read `200`, approval `200`, Ingest `completed`, cleanup dry-run/apply, post-cleanup `404`, and residual count `0` all passed.

## Failure

The production WebSocket handshake succeeded, but the synthetic `chat.send` exchange did not receive an application response. The gateway/proxy closed with code `4401` after the probe sent an empty auth token. This is recorded as a WebSocket authentication/protocol gate failure; it is not evidence of candidate application regression. No further acceptance write was started.

Failure-window ingest capture was not triggered because Ingest completed successfully and cleanup had already reconciled the synthetic scope. Capture persistence remains ready for a future ingest failure.

## Rollback and Cleanup

Synthetic cleanup completed before the WebSocket probe with residual `0`. The approved persistent checkpoint restored the baseline image. Post-rollback Health was HTTP `200`, Celery had 2 nodes, tasks/queues were empty, and the temporary identity returned HTTP `403` after removal. No stuck task retry, manual Redis/ledger mutation, migration, restore, WP2, real instrument access, or secret evidence occurred.

## Follow-up

Do not retry production from this window. Diagnose the production WebSocket auth/protocol contract in isolated scope first, including the required auth frame/token forwarding and expected response event. Do not change the approved candidate or classify this as an application regression without isolated evidence.
