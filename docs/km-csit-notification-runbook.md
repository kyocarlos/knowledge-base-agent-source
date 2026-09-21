# KM-CSIT Notification Receiver Runbook

This is a KM-only test runbook. Do not point it at CSIT or Production.

1. Create a disposable working directory and fixture file.
2. Set `KM_CSIT_NOTIFICATION_ENABLED=true`, a disposable test token, and
   `KM_CSIT_NOTIFICATION_ELIGIBILITY=test-allow` (or `test-hold`).
3. Start the KM API with an isolated SQLite database and an injected
   allowlisted fixture resolver/processor.
4. POST the example event from the OpenAPI document with the test bearer.
5. Confirm `202`, then query the event status. A `completed` state means the
   processor returned successfully; it is not a CSIT publication assertion.
6. Repeat the same event concurrently and confirm one receipt/job. Change one
   field and confirm `409`.
7. Stop the dispatcher before processing, restart it, and drain pending rows.
8. Verify document/version/checksum/provenance and search in isolated runtime.
9. Capture sanitized event/job evidence, then remove the database, staging,
   package, vector and graph records. Residual is `UNKNOWN` unless each store
   is independently queried and proves zero.

No Browser Cookie, CSIT account, Production token, Production volume, or
Production deployment is permitted by this runbook.
