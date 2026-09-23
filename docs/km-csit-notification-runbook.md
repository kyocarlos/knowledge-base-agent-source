# KM-CSIT Notification Receiver Runbook

This is a KM-only test runbook. Do not point it at CSIT or Production.

1. Create a disposable working directory and fixture file.
2. Set `KM_CSIT_NOTIFICATION_ENABLED=true`, a disposable test token, and
   `KM_CSIT_NOTIFICATION_ELIGIBILITY=test-allow` (or `test-hold`).
3. Configure `KM_CSIT_NOTIFICATION_FIXTURES_JSON` with a fixture ID, an
   absolute local test-file path, and its SHA-256. Event payloads contain only
   the fixture ID; they can never select a local path or bypass the checksum.
4. Start web and the ingest worker from the same image. Set
   `KM_TIMESERIES_DATABASE_URL` only on those two services, apply migrations
   using the controlled migration account before enabling the receiver, and
   keep the API/worker from issuing DDL.
5. POST the example event from the OpenAPI document with the test bearer.
6. Confirm `202`, then query the event status. `received` only proves durable
   receipt; `queued` means the existing KM worker was accepted; `completed`
   means the existing worker completed its parser, Neo4j, Qdrant and
   TimescaleDB steps. It is not a CSIT publication assertion.
7. Repeat the same event concurrently and confirm one receipt/job. Change one
   field and confirm `409`.
8. Stop the dispatcher before processing, restart it, and drain pending rows.
   For an ingest-worker interruption, rely on the Celery task's late-ack
   recovery, then verify receipt status and the existing task state converge.
9. Verify document/version/checksum/provenance and search in isolated runtime.
10. Capture sanitized event/job evidence, then remove the receipt database,
    staging, registry, Redis task state, package, vector, graph and
    Timescale rows. Residual is `UNKNOWN` unless every store is independently
    queried and proves zero.

No Browser Cookie, CSIT account, Production token, Production volume, or
Production deployment is permitted by this runbook.
