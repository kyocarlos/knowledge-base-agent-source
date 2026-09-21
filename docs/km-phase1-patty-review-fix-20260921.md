# KM Phase 1 Patty review fixes — 2026-09-21

This branch implements the KM-owned, testable portion of
`AI_KM_Phase1_修改清單_20260921.xlsx`.

## Implemented in this batch

- Canonical `ai_km_knowledge_v1` validator with required fields, stable
  document/version/chunk identity, package digest, and draft-by-default
  lifecycle.
- Qdrant point IDs derived from logical identity rather than filename/index;
  new writes are `draft` and `is_current=false` until a technical publish.
- Stage/commit/rollback coordinator for injected Qdrant/Neo4j writers; a
  partial required-store result cannot be reported as published.
- Receiver SQLite migration for `claimed_at`, `lease_until`,
  `heartbeat_at`, `attempt_count`, and `worker_id`.
- Atomic receiver dispatch claim, stale-processing reclaim, claim-bound finish,
  explicit processor result semantics, and status query visibility.
- MIME/signature registry with parser name/version; known binary extension
  mismatches fail closed. Standalone image formats are included in the watch
  allowlist. Empty conversion output fails the quality gate.
- Focused unit/contract tests and CI path coverage for the above.

## Deliberately not frozen or claimed complete

The workbook marks the following as joint CSIT/KM decisions or external
runtime evidence, so this branch leaves replaceable seams and does not invent
the answer:

- Published trigger, event/DTO/ID mapping, Project/Case/Task mapping, ACL
  mapping, formal S2S authentication, file delivery, checksum authority, and
  completion callback/query semantics.
- Real CSIT sender/download, cross-system UAT, production credentials,
  Production database, and Production deployment.
- OCR/Vision provider configuration for scanned PDFs/images, full structured
  DOCX/PPTX enrichment, TimescaleDB ingestion/query/retention, unified human
  RBAC, Report Center, Booking, and Validation Request workflows.

## Evidence

The isolated runtime test command is:

```text
python -m pytest -q tests
```

The local isolated run completed with `53 passed` after installing the
repository's CI dependencies. Compile, YAML parsing, and `git diff --check`
also passed. No CSIT endpoint, Production secret, Production database, or
Production deployment was used.

