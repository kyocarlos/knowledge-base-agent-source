# CSIT → KM Manifest Pull V1

## Current decision

CSIT remains the system of record.  After a Test Report changes to
`ReviewStatus=Approved` and `IsFinal=true`, CSIT rebuilds `km-manifest.json`.
The first KM integration uses Pull; CSIT does not push a webhook, message, or
outbox event yet.

The formal KM V1 endpoint is:

```text
GET /api/km/v1/projects/{projectId}/manifest
```

The ordinary Module → Record traversal is used only to discover Project IDs;
the KM adapter then calls this dedicated endpoint.  It does not modify the
general File DTO, read the NAS Project package, or treat `relativePath` as a
server-local file path.  CSIT still needs to implement this endpoint in the
Stage runtime.

## Import rule

- TestReport: import only when `ReviewStatus=Approved` and `IsFinal=true`.
- Attachment: may be imported as a source document without the report approval
  workflow, subject to the same file/hash/path validation.
- `DocumentId` is the stable logical document identity.
- `FileId + Version` identifies one uploaded revision.
- `relativePath` is metadata only; KM must download through the CSIT API and
  must never use a CSIT server-local file path.

## KM mapping and storage boundary

The validated entry is mapped to the existing KM source metadata, then passed
to the existing staging/parser/chunk/embedding pipeline.  Clean text chunks
and retrieval metadata go to Qdrant; entities, relationships, and provenance
go to Neo4j.  Numeric time-series data is routed separately to TimescaleDB.
CSIT credentials, CSIT PostgreSQL, NAS, Neo4j, and Qdrant are not exposed to a
browser or external agent.

## Pull and tracking behavior

- The adapter is bounded by configurable `page_size` and `max_pages`.
- Missing core identity/lifecycle fields are skipped fail-closed with a
  sanitized reason; KM does not invent IDs or statuses.
- The actual file is still downloaded through
  `GET /api/files/{fileId}/download`, then KM computes SHA-256 and compares it
  with the manifest field.
- KM tracks `DocumentId`, `FileId`, `Version`, `SHA256`, status, error, and
  `IngestedAt` in its local registry.
- A missing entry in a later Pull is not a withdrawal and never deletes a
  Qdrant point or Neo4j node.  Withdraw/Tombstone/change-feed are deferred.
- The current adapter is read-only and does not send an ingest acknowledgement
  back to CSIT.

## Remaining CSIT implementation tasks

1. Implement the dedicated KM V1 manifest endpoint and return the frozen
   fields in `config/csit_km_v1_contract.json`.
2. Create the fixed UAT Dataset with expected ingest, SHA256, and CSIT IDs.
3. Define the future service authentication contract; current Cookie login is
   Stage-only.
4. Define future changed-since/change-feed and Withdraw/Tombstone semantics.

The implementations in `src/csit/manifest.py` and `src/csit/pull.py` are the
fail-closed validation and traversal front doors.  They do not write Neo4j or
Qdrant; the existing KM ingest pipeline remains the only write path.

## KM-owned post-Pull ingest

`src/csit/ingest.py` is the KM-side handoff after a manifest entry passes the
lifecycle filter.  It records `discovered`, downloads only through the mapped
CSIT File download API, verifies both byte length and SHA-256, stages below a
caller-owned directory, then calls `run_document_pipeline`.  The same
`DocumentId/FileId/Version/SHA256` revision is idempotent after a successful
ingest; a later Pull missing an entry still does not delete knowledge.

The local fixture at
`tests/fixtures/csit_km_uat_manifest.json` is a KM contract fixture, not the
fixed CSIT Stage UAT Dataset.  It verifies the A/B revision lifecycle and is
safe to run without CSIT credentials, Production data, Qdrant, or Neo4j.

For a real Stage run, use `scripts/run_csit_km_manifest_pull.py`.  It is
dry-run by default and prints only IDs/counts; `--execute` is an explicit
write-to-KM action that downloads through the CSIT API and invokes the
existing pipeline.  The command requires mounted secret files and the CSIT
CA certificate; it does not accept credentials on the command line.

The shared service boundary is `src/csit/sync.py`.  It is intentionally
usable by the CLI, a future Celery task, or an API-triggered administrative
job without duplicating the Pull/ingest logic.  Batch results expose only
counts, IDs, statuses, and sanitized error codes.

## Stage observation (2026-09-18)

Using the already mounted `kb-web` Stage runtime, the provided KM Stage
credential matched the mounted Secret and the read-only traversal completed:
4 enabled modules, 8 records, 1 case, 1 task, and 1 task file.  The observed
file DTO keys included `documentId`, `fileKind`, `isFinal`, `reviewStatus`,
`sha256`, `versionNo`, `createdAt`, `filePath`, and `id`, but did not include
the currently expected names `fileId`, `version`, `uploadedAt`, or
`relativePath`.

This is a difference between the general Stage DTO and the dedicated KM
Contract.  The general DTO is not eligible for automatic KM ingest.  The KM
adapter must call the dedicated manifest endpoint instead.

## Stage recheck (2026-09-18)

From the current `kb-web` runtime, the protected Cookie login and enabled
module/Project discovery returned successfully.  A read-only request to
`GET /api/km/v1/projects/{projectId}/manifest` returned HTTP 404.  Therefore
the KM adapter is ready, but a real manifest Pull and downstream ingest cannot
be claimed until CSIT deploys that endpoint.

Patty subsequently confirmed the semantic mappings: `id → fileId`,
`versionNo → version`, and `createdAt → uploadedAt`.  KM now applies only
these three aliases at the adapter boundary and drops internal path fields.
`relativePath` remains mandatory and must be supplied by the formal KM V1
Contract; it is never derived from `filePath`.
