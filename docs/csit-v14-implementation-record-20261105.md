# CSIT × AI KM spec v1.4 — KM-side implementation record (2026-11-05)

Spec: `CSIT_AI_KM_介接規格_v1.4_完整雙向REST_API.docx` (v1.4, 2026-11-05). Branch `feature/csit-spec-v14-20261105`, built on the v1.3 + simulator branch.
Status: **code and tests only. Not deployed to DA40 or TEST. Not verified against the real CSIT.**

## What the spec added to v1.3

| Spec § | Contract | KM now |
|---|---|---|
| 4 | `POST /csit/v2/document-jobs` — verification attachments, vendor files, equipment attachments, every format | `v2_api.py`, `v2_repository.submit_job`, `v2_pipeline.py` |
| 5.1–5.3 | `POST /km/v2/document-jobs/status` (Processing / Completed + 5.2 result / Failed + code) | `v2_models.build_job_callback`, outbox kind `ingestion2` |
| 5.4 | `POST /km/v2/analysis-results` for Test Report | built, **off by default** (open question 1) |
| 6.1 | version replacement via `supersedes`; old index retired only after the new one is Completed | `V2Pipeline.reconcile_supersede`, `supersede_pending` |
| 6.2 | `POST /csit/v2/document-metadata-changes` + `POST /km/v2/document-metadata-changes/status` | `submit_change`, `V2Processor.change_one`, kind `change` |
| 7.2–7.3 | `POST /csit/v2/document-deletions` + `POST /km/v2/document-deletions/status` | `submit_deletion_v2`, shared deletion worker, kind `deletion2` |
| 3.2 | authorised GET for vendor files and equipment documents | `DocLibClient.download_v2` (route per source type) |
| 3.1 | `Idempotency-Key` = eventId / callbackId / changeId / deletionRequestId | checked on intake; sent on v2 callbacks |

v1 routes, DTOs and the v1.3 tables are unchanged. v1 callbacks still go out without an `Idempotency-Key`.

## Behaviour worth knowing

- **Nothing is refused for its format.** The job is accepted, then Failed with a code: `UNSUPPORTED_FORMAT` (images, ZIP, unknown extension, no OCR/vision), `ENCRYPTED_DOCUMENT` (password-protected Office/PDF), `CORRUPT_FILE`, `MALWARE_DETECTED` (executable content), `PARSER_ERROR`, `SHA256_MISMATCH`, `FILE_TOO_LARGE`. Readable: txt, csv, md, pdf, docx, xlsx, pptx (slide text).
- **Errors**: v2 contract violations are `400` (v1.3 routes keep `422`); tombstoned `410`; unknown document on a metadata change `404`; conflicts (same eventId with another file, a second active job for the same source version, stale `sourceRevision`, wrong sha256 / `canonicalIngestionEventId` on a deletion) `409`; non-JSON body `415`.
- **One active ingestion per (sourceType, sourceEntityId, version)**; a Failed job can be replaced by a new event. Same name or same SHA256 from different sources are separate jobs.
- **Metadata changes** update the index payload only (no download, no re-extraction), in `sourceRevision` order, and wait while the document's ingestion is running. A change on a document that has no completed index ends Failed `TARGET_NOT_INDEXED`.
- **Deletion** uses the same exact-version tombstone as v1; a v1 deletion of a verification attachment now also cleans its v2 data. Graph/numeric stores are only required for Test Report data, so a v2 deletion works in the simulator mode (no Neo4j/Timescale).
- **Scopes**: inbound accepts the v1.3 scope `km.ingestion.submit` and the v1.4 names per endpoint (`km.ingestion.write`, `km.metadata.write`, `km.deletion.write`). Outbound scopes default to the v1.3 names; set `KM_CSIT_OUTBOUND_SCOPES` once CSIT IT confirms the v1.4 mapping (`csit.documents.read,csit.km.status.write,csit.km.deletion-status.write`). The outbound token must carry exactly the configured set.
- All of it is behind the existing `KM_CSIT_DOCLIB_ENABLED` switch.

## Open questions for CSIT (Patty)

1. **Test Report `analysis-results` (§5.4)**: `sourceEntityId` must be `ModuleCaseFile.Id`, but the v1 ingestion payload carries no such id (and v1 rejects unknown keys). Is it the same as `documentId`? Also: is `csitJobId` the v1 `eventId`? Until answered the feature stays off; with `KM_CSIT_ANALYSIS_SOURCE_ENTITY=documentId` it uses `documentId` and the v1 `eventId`.
2. **Images (PNG/JPG)**: KM has no OCR/vision, so they end `Failed UNSUPPORTED_FORMAT`. Acceptable, or should KM return Completed with `method=None`, `chunkCount=0`?
3. **Event types for replacements of Test Report / document-library files through v2** are not named in the spec; only the four archived events are accepted.
4. `reasonCode` list is open in the spec (`SourceDeleted`, `VersionSuperseded`, `AdministrativeCleanup` …); any 1–128 char value is accepted.
5. Scope names (above).

## Not done / limits

- LLM extraction is still off, so `documentType` is `Other` and `summary`/`keywords` empty; `sourceSpecific` carries only evidence KM has (sheet names), the rest is empty. `extractedTables` is `[]`.
- The vectors are written to the document-library collection; KM search does not read that collection yet (same as v1.3).
- The CSIT simulator does not speak v2 yet, so there is no end-to-end run against it. Contract tests use a fake CSIT.
- Not run against real Qdrant/Neo4j/Timescale; the 49 failures/errors in `tests/csit_v1` that already existed on the base branch (Neo4j, JWKS/network) are unchanged.

## Deployment (when approved)

1. Apply `migrations/20261105_csit_integration_v2.sql` to `km_control` (additive; it replaces two CHECK constraints) and to the `csit_sim` schema (`setup-sim.sh` now includes it).
2. Build the api and worker images from this branch (overlay pattern as for v1.3), `csit-mode.sh reapply`.
3. Ask CSIT to switch the new endpoints on in their 7444 allow-list: GET `vendor-files/{id}/content`, `equipment-documents/{id}/content`, and the v2 POST callbacks.
