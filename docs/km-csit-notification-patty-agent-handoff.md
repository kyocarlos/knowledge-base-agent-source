# Patty Agent handoff: KM-CSIT-NOTIFY-PREP

`CONTRACT_STATUS = KM_PROPOSED_NOT_YET_JOINTLY_CONFIRMED`
`PATTY_AGENT_NOTIFICATION = NOT_SENT`

## KM delivered in this PR

- Proposed `POST /api/v1/integrations/csit/events` and protected status query.
- Fail-closed receiver configuration and replaceable source-auth provider.
- SQLite durable receipt, atomic duplicate handling, conflict `409`, and
  recoverable pending dispatch.
- Allowlisted fixture resolver with checksum verification.
- Processor seam for the existing KM validation/Knowledge Package/ingest path;
  no second review or ingestion implementation.
- Focused contract/negative/concurrency tests and KM-only CI.

## Patty decisions still required

1. Approved or Published trigger and the final event name/schema.
2. CSIT DTO to `document_id`, version, file reference, checksum, ACL and
   publication mapping.
3. Formal S2S authentication and rotation process.
4. CSIT push artifact versus KM download, retry, and completion semantics.
5. Disposable fixed UAT dataset with expected ingest/current/search results.

The sender and file source are simulated in this PR. Real CSIT integration,
cross-system UAT, and Production deployment were not executed or authorized.
