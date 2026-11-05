# CSIT × AI KM spec v1.4 / v1.4.1 — KM-side implementation record (2026-11-05)

Spec: `CSIT_AI_KM_介接規格_v1.4_完整雙向REST_API.docx` (v1.4) as corrected by `…v1.4.1_Anderson疑義定案版.docx` and `CSIT_KM_v1.4.1_Anderson_11題正式回覆.md` (appendix C wins where they differ). Branch `feature/csit-spec-v14-20261105`, built on the v1.3 + simulator branch.
Status: **code and tests only. Not deployed to DA40 or TEST. Not verified against the real CSIT.**

## What the spec added to v1.3

| Spec § | Contract | KM now |
|---|---|---|
| 4 | `POST /csit/v2/document-jobs` — verification attachments, vendor files, equipment attachments, every format | `v2_api.py`, `v2_repository.submit_job`, `v2_pipeline.py` |
| 5.1–5.3 | `POST /km/v2/document-jobs/status` (Processing / Completed + 5.2 result / Failed + code) | `v2_models.build_job_callback`, outbox kind `ingestion2` |
| 5.4 | `POST /km/v2/analysis-results` for Test Report | built; needs the Correlation Resolver, **off by default** |
| 6.1 | version replacement via `supersedes`; old index retired only after the new one is Completed | `V2Pipeline.reconcile_supersede`, `supersede_pending` |
| 6.2 | `POST /csit/v2/document-metadata-changes` + `POST /km/v2/document-metadata-changes/status` | `submit_change`, `V2Processor.change_one`, kind `change` |
| 7.2–7.3 | `POST /csit/v2/document-deletions` + `POST /km/v2/document-deletions/status` | `submit_deletion_v2`, shared deletion worker, kind `deletion2` |
| 3.2 | authorised GET for vendor files and equipment documents | `DocLibClient.download_v2` (route per source type) |
| 3.1 | `Idempotency-Key` = eventId / callbackId / changeId / deletionRequestId | checked on intake; sent on v2 callbacks |

v1 routes, DTOs and the v1.3 tables are unchanged. v1 callbacks still go out without an `Idempotency-Key`.

## Behaviour worth knowing

- **Nothing is refused for its format.** (A readable file that yields no text is `Failed EMPTY_EXTRACTION`.) The job is accepted, then Failed with a code: `UNSUPPORTED_FORMAT` (images, ZIP, unknown extension, no OCR/vision), `ENCRYPTED_DOCUMENT` (password-protected Office/PDF), `CORRUPT_FILE`, `MALWARE_DETECTED` (executable content), `PARSER_ERROR`, `SHA256_MISMATCH`, `FILE_TOO_LARGE`. Readable: txt, csv, md, pdf, docx, xlsx, pptx (slide text).
- **Errors**: v2 contract violations are `400` (v1.3 routes keep `422`); tombstoned `410`; unknown document on a metadata change `404`; conflicts (same eventId with another file, a second active job for the same source version, stale `sourceRevision`, wrong sha256 / `canonicalIngestionEventId` on a deletion) `409`; non-JSON body `415`.
- **One active ingestion per (sourceType, sourceEntityId, version)**; a Failed job can be replaced by a new event. Same name or same SHA256 from different sources are separate jobs.
- **Metadata changes** update the index payload only (no download, no re-extraction), in `sourceRevision` order, and wait while the document's ingestion is running. A change on a document that has no completed index ends Failed `TARGET_NOT_INDEXED`.
- **Deletion** uses the same exact-version tombstone as v1; a v1 deletion of a verification attachment now also cleans its v2 data. Graph/numeric stores are only required for Test Report data, so a v2 deletion works in the simulator mode (no Neo4j/Timescale).
- **Scopes**: see the v1.4.1 table (answer 4). The outbound token must carry exactly the configured set.
- All of it is behind the existing `KM_CSIT_DOCLIB_ENABLED` switch.

## v1.4.1 (CSIT's answers to the 11 questions): what changed in KM

| Answer | Decision | KM now |
|---|---|---|
| 1, 2 | `sourceEntityId` ≠ `documentId`; `csitJobId` ≠ `eventId`; both come from the new **Correlation Resolver** `GET /api/integrations/km/v2/test-report-correlations/{eventId}?documentId=&version=&kmJobId=` (CSIT task C, not deployed) | The `documentId` guess is gone. `analysis-results` is sent only after CSIT acknowledged the v1 Completed status **and** the Resolver answered 200 with a response that repeats the request, has valid ids and the same SHA256 KM downloaded. 404/409/410/401/403/mismatch are recorded as Skipped with the reason and nothing is sent; 429/5xx/timeout back off, then Skipped. Off until `KM_CSIT_ANALYSIS_RESULTS_ENABLED=true` |
| 3 | 7444 allow-list status | Operational: GET vendor-files / equipment-documents (task B), POST metadata-changes/status (C), POST deletions/status (D) are not open yet; document-jobs/status and analysis-results are |
| 4 | Official scopes: in `km.ingestion.write` / `km.metadata.write` / `km.deletion.write`; out `csit.document.read` (**singular**) / `csit.km.status.write` / `csit.km.deletion-status.write`; v1 scopes unchanged; no one-sided switch | Inbound accepts the v1 scope and the v2 scope per endpoint. Outbound default stays v1.3. After the joint M2M contract test set `KM_CSIT_OUTBOUND_SCOPES=csit.document.read,csit.km.status.write,csit.km.deletion-status.write` (plus `csit.ingestion.status.write` while v1 callbacks are still sent). The plural `csit.documents.read` in the earlier draft was wrong |
| 5 | `TestReportCommitted` and `DocumentLibraryFileUploaded` are accepted on `/v2/document-jobs` only for a new version with `supersedes` | Added to the closed event list; without `supersedes` → 400; a source version already delivered through v1 → 409 `V1_JOB_EXISTS`. Replacing a v1 Test Report also retires its report-collection vectors. `km_csit_v2_jobs.source_type` allows all five sources |
| 6, 7 | Images / ZIP / unknown: accept, then `Failed UNSUPPORTED_FORMAT`, `retryable=false`; never `Completed(None, 0)` | Already so; additionally **a file with no extractable text is now `Failed EMPTY_EXTRACTION`** (it used to be Completed with 0 chunks) |
| 8 | Failure codes, integrity/malware not retried | Unchanged, all `retryable=false` |
| 9 | v2 `reasonCode` is a closed, case-sensitive enum | `SourceDeleted`, `VersionSuperseded`, `AdministrativeCleanup`; anything else → 400. v1 route unchanged |
| 10 | No LLM: Other / null / [] is fine, `sourceSpecific` an object | Unchanged; still not an AI-extraction acceptance |
| 11 | 409 must not be retried four times | A 409 on `document-jobs/status`, `document-metadata-changes/status`, `document-deletions/status` is **not retried** (the callback ends Failed, one WARNING with eventId / csitJobId / kmJobId). `analysis-results` is retried with backoff only when the answer says `job_not_completed`. v1 callbacks keep their old behaviour; 429/5xx/timeout still retry |

## Still open / waiting on CSIT

- Correlation Resolver (task C): until it exists the Test Report analysis-results stays off.
- 7444: GET vendor-files and equipment-documents (B), metadata-changes/status (C), deletions/status (D).
- Joint M2M contract test before switching `KM_CSIT_OUTBOUND_SCOPES`.
- The body shape of the `job_not_completed` 409 is not specified; KM looks for that text in the response.

## Not done / limits

- LLM extraction is still off, so `documentType` is `Other` and `summary`/`keywords` empty; `sourceSpecific` carries only evidence KM has (sheet names), the rest is empty. `extractedTables` is `[]`.
- The vectors are written to the document-library collection; KM search does not read that collection yet (same as v1.3).
- The CSIT simulator speaks v1.4 / v1.4.1 (see `tools/csit_simulator/README.md`); the local drill runs 84 checks against the real KM code on a local PostgreSQL. Not run against the deployed KM.
- Not run against real Qdrant/Neo4j/Timescale; the 49 failures/errors in `tests/csit_v1` that already existed on the base branch (Neo4j, JWKS/network) are unchanged.

## Deployment (when approved)

1. Apply `migrations/20261105_csit_integration_v2.sql` to `km_control` (additive; it replaces two CHECK constraints; not applied anywhere yet, so it was edited in place for v1.4.1) and to the `csit_sim` schema (`setup-sim.sh` now includes it).
2. Build the api and worker images from this branch (overlay pattern as for v1.3), `csit-mode.sh reapply`.
3. CSIT tasks B/C/D open the remaining 7444 routes; do not enable CSIT `KmIntegration.Enabled` early.
