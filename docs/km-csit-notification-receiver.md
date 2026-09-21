# KM-CSIT Notification Receiver v1

Status: `KM_PROPOSED_NOT_YET_JOINTLY_CONFIRMED`.

The receiver accepts a proposed CSIT event only when all of these are
configured: `KM_CSIT_NOTIFICATION_ENABLED=true`, a non-empty
`KM_CSIT_NOTIFICATION_AUTH_TOKEN`, and an explicit test-only eligibility mode.
The default is disabled and fail-closed. The token adapter is intentionally a
replaceable test seam, not a CSIT S2S decision.

## Processing boundary

```text
authenticated event -> SQLite durable receipt -> recoverable pending row
  -> eligibility policy -> allowlisted fixture/file resolver
  -> existing KM ingest adapter -> package/lifecycle -> Qdrant/Neo4j/Search
```

`202 Accepted` means only that the event and dispatch intent were durably
stored. It does not mean downloaded, ingested, current, published, or
searchable. A recovery worker calls `NotificationReceiver.dispatch_pending()`;
the durable row remains pending if the worker or broker is unavailable.

The receiver uses `source_identity + event_id` as its idempotency key. JSON key
ordering does not create a conflict. A different payload with the same key is
`409` and never overwrites the original. File references are resolved through
an allowlisted resolver; arbitrary URLs, absolute paths, and traversal are not
accepted. Version/checksum validation occurs before the existing KM pipeline.

## Configuration

```text
KM_CSIT_NOTIFICATION_ENABLED=false
KM_CSIT_NOTIFICATION_AUTH_TOKEN=(unset)
KM_CSIT_NOTIFICATION_ELIGIBILITY=disabled
KM_CSIT_NOTIFICATION_DB=data/csit-notification.sqlite3
```

`test-allow` and `test-hold` are disposable test modes only. There is no
production secret, browser cookie, real CSIT endpoint, or CSIT database in
this change.

## Reuse reconciliation

| Capability | Reuse/decision |
| --- | --- |
| Existing KM ingest | Receiver exposes a processor adapter; production wiring must call the existing validation, Knowledge Package, lifecycle, converter, chunk, embedding, Qdrant, Neo4j and Search pipeline. |
| Existing CSIT Pull | Remains a separate reconciliation/backfill path; it is not used as the notification API. |
| Existing auth | Browser/Reviewer auth is not reused as S2S. The receiver has a minimal replaceable source-auth interface. |
| Existing job state | Event status and `job_id` are persisted in the durable receiver store; the processor adapter owns the existing ingest task correlation. |
| Lifecycle | No delete-first or current-version overwrite is performed by the receiver. |

The current branch contains the local baseline commit used for this
maintenance branch; it must not be described as merged into `main`.

## Known gaps requiring joint confirmation

- Approved versus Published trigger and formal event name/schema/ID mapping.
- Formal CSIT-to-KM S2S authentication and credential rotation.
- File push versus KM download and checksum/ACL/publication source.
- Completion query/callback and fixed UAT dataset.

