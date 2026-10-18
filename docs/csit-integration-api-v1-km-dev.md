> 本文件保留原實作說明；最新 runtime contract、build 與交接驗證以 [Patty 交接指南](handoff/PATTY_DEVELOPMENT_HANDOFF.md) 為準。

# CSIT ↔ KM Integration API Contract v1 — KM DEV

Status: CONTRACT FIX DEPLOYED; FRESH CSIT SAFE PROBE PENDING (2026-10-13). Prior sections describe historical acceptance; latest disabled state and number contract are below.

## Boundary and deployment

Only CSIT TestReportCommitted Test Reports are accepted. Human OIDC/binding remains in the unchanged Control Auth container. A separate private FastAPI service exposes exactly POST /api/integrations/csit/v1/ingestion-jobs through the existing DEV 3030 ingress. It uses the existing DEV Control PostgreSQL metadata DB. No second runtime database is created.

The DEV API is deployed with KM_CSIT_ENABLED=false. Anonymous and human-cookie requests return 401; bearer requests without approved M2M configuration return 503. The durable worker is implemented, its image built, and its m2m-ready compose profile stays OFF. Test authentication is Python fixture injection only; there is no test-auth environment switch or runtime fallback.

A valid, authorized contract request persists a job and returns 202 (verified using test authentication/fake CSIT). This does not claim a live authenticated 202 while service credentials are pending.

## Persistence, recovery and partial failure

migrations/20261007_csit_integration_v1.sql was applied idempotently to the verified DEV Control DB management channel. Runtime startup performs read-only schema checks, never migration DDL. Existing role privileges were not increased.

The DB unique key is (source_system,document_id,version), with INSERT ON CONFLICT and immutable-metadata conflict detection. Different eventId retries reuse the existing job. Each source version is preserved.

Workers claim with FOR UPDATE SKIP LOCKED, a persisted expiring lease, unique fencing token and heartbeat. Stale workers cannot checkpoint or complete. Download / extraction temporary artifacts are lease-specific, so overlapping attempts cannot clobber each other's staging paths.

Canonical typed extraction artifacts are checksummed and checkpointed before writers. Writers use stable source/version IDs and upserts/MERGE. A failed phase persists Failed plus its sanitized failure callback; configured retry reuses completed writer checkpoints. No cross-store ACID transaction is claimed.

Callbacks have a separate durable ordered outbox, separate claims/leases and an independent sender loop. Delivery retry never changes a completed ingestion back into a runnable job. Temporary 409 correlation conflicts are retried within the configured callback budget to handle the race where CSIT is still saving the 202 jobId; mismatched correlation never updates a different source event. 401/403 are permanent authorization failure; 429/5xx/timeouts are retryable.

## Files and deterministic routing

The HTTP client streams bounded chunks, validates MIME, Content-Disposition filename, declared/actual size and configured maximum, then parser compatibility/signature. Filenames are never storage identities. ZIP-based Office inputs are checked for traversal and bounded members/expanded size/compression ratio. No source file is executed and no CSIT DB/NAS/physical path is read.

PDF/DOCX reuse the existing FileConverter/MarkItDown path with implicit LLM defaults disabled. TXT/CSV and XLSX/openpyxl produce text plus discovered normalized tables. Unsupported formats or missing parsers fail UNSUPPORTED_DOCUMENT_FORMAT.

Configured exact table recognizers extract timestamp + iPerf/throughput/KPI values and explicit units into finite, timezone-aware typed metrics. Unknown tables remain table/text content. Recognized raw numeric series do not become Qdrant text. Controlled optional extraction returns a typed schema and never receives writers/tools.

Routing is code:
- metadata/job/lineage/parser and extraction versions/checkpoints/storage references -> existing Control DB;
- chunk text and embeddings -> Qdrant, using existing content/retrieval field conventions plus complete lineage;
- typed entities and relations -> Neo4j, with unique source/version identity constraints;
- validated numeric points -> TimescaleDB, with hypertable source/version point upsert;
- originals/canonical extraction/normalized artifacts -> configured KM-owned storage.

Writer target settings and graph/Timescale migrations must be configured/applied to the approved KM DEV data zone before a future live worker activation. In this round graph/Timescale migrations and real writes were tested only in disposable isolated containers. Original data-zone stores were not modified. No retention or deletion policy was introduced.

## Exact CSIT callback mapping

Canonical source paths supplied by the user are on another host:
C:/CSIT_System/SIT.DepartmentSystem.Web/Services/KmIntegration/KmIntegrationContracts.cs
C:/CSIT_System/SIT.DepartmentSystem.Web/Controllers/KmIntegrationController.cs
C:/CSIT_System/SIT.DepartmentSystem.Web/Entities/KmIntegrationOutbox.cs

These paths are unavailable on the KM work host. Exact mapping uses the user's supplied current v1 DTO definition, not a claim that those files were read.

| CSIT field | KM mapping |
| --- | --- |
| jobId | persisted job_id; identical to POST 202 response |
| sourceSystem | source_system = CSIT |
| documentId | document_id |
| version | positive source version integer |
| status | only Processing / Completed / Failed; never internal phases |
| timestamps.updatedAt | committed job state updated_at, ISO8601 with timezone |
| timestamps.completedAt | completed_at, Completed only |
| error.code | sanitized last_error_code, Failed only |
| error.message | sanitized last_error_message, Failed only |

No eventId, top-level updatedAt/completedAt, stack trace or physical path is added to the callback. CSIT formal report Committed/approval status is never modified by KM. Fake CSIT verifies all four correlation fields and rejects mismatches.

## M2M requirements

M2M CLIENT CREDENTIALS REQUIRED FROM SHARED IDENTITY.

Read-only discovery advertises client_credentials, but approved integration clients/scopes/audiences and protected service secret references are not available. The user also confirmed formal integration M2M is still pending.

Proposed clients (names must be agreed/provisioned by Shared Identity):
- csit-km-ingestion-dev: resource/audience km.integration.dev, scope km.ingestion.submit.
- km-csit-integration-dev: resource/audience csit.integration.dev, scopes csit.document.read and csit.ingestion.status.write.

Agree the exact access-token issuer, resource/audience, asymmetric signing/JWKS, client identity claim and reliable client_credentials/service identity marker. JWT validation is fail-closed on signature, issuer, audience, expiry, required timestamps, approved client identity, service marker and scope. Existing human km-dev registration/secret is not used.

Token endpoint client_secret_basic is OAuth client authentication for the client_credentials grant, not Basic authentication on KM/CSIT integration APIs. Only dedicated protected outbound service credentials may be configured.

Do not call protected CSIT APIs, enable CSIT integration or activate the worker until M2M and both sides are ready and the user separately authorizes live DEV E2E.

## Verification and rollback

95 new tests and 30 existing OIDC/binding tests: 125 passed, 0 failed. The three-zone grant regressions use isolated automated fixtures; no fresh human password login was simulated. Original Human CORE evidence remains in project memory. Existing service container/image/env identities and OIDC source hashes were verified unchanged; the DEV ingress change is one exact protected integration location with original routes byte-preserved. Source/Git status remains STALE / UNCOMMITTED; no approved new source commit is claimed.

Rollback: restore protected nginx.before.conf to the DEV runtime config, run nginx -t and reload, then stop only the new integration API project. Preserve metadata jobs/checkpoints/callback evidence; do not drop tables with accepted jobs. No existing OIDC/web/data-zone containers need recreation. No rollback was executed because validation passed.

Safe evidence is under outputs/csit-km-integration-v1-20261007 and the protected .km-control/csit-integration-v1-20261007 directory. Runtime/test DB connection credentials are outside source; test credentials and disposable services are cleaned after verification. No password, token, authorization code, Client Secret or sensitive source-file contents are present in delivered evidence.


## 2026-10-12 outbound provider readiness

The DEV request remains client_credentials with client_secret_basic and only grant_type/scope. No audience or resource form field is sent. The issuer returns HTTP 200 with access_token, expires_in and token_type, omitting the optional response scope field. Outbound scope authorization now comes from a signature-verified JWT; a present response scope field must also match. KM_CSIT_AUDIENCE remains inbound-only. The separate protected KM_CSIT_OUTBOUND_AUDIENCE setting is csit.integration.dev. Outbound tokens must pass JWKS signature, exact issuer/audience, exp/iat, principal_type=service, exact client_id/sub and both dedicated scopes before caching. Sanitized OAuth errors retain only status, safe error code/description; secrets, Basic/Bearer values and tokens are redacted.

144 isolated CSIT v1 and passwordless binding tests passed. One diagnostic token request and one post-fix token request were made, with no business API calls. The updated API image is km-csit-integration:v1-token-scope-20261012; the corresponding worker image is built and configured but the worker remains OFF. KM_CSIT_ENABLED remains false. This readiness supersedes the earlier pending-credential notes; live E2E and enablement still require separate authorization. No commit/push.


## 2026-10-12 direct inbound authentication probe while disabled

The CSIT client secret stays in CSIT. Do not hand off a raw token file. CSIT sends a fresh normal HTTP Bearer token directly to the existing ingestion endpoint with schema-invalid JSON {}. Fully configured inbound JWT verification stays active while KM_CSIT_ENABLED=false. A valid service token plus invalid body returns 422; a valid ingestion contract remains blocked with 503 before Repository.submit. The worker stays OFF, with before/after job counts checked through read-only metadata queries.

Runtime service identity uses the protected principal_type=service configuration. The previous gty=client_credentials configuration rejects an otherwise valid service JWT without gty; this was reproduced in isolated tests. The original Live request cannot be attributed conclusively because its auth/access logs were disabled. Do not label the reconstructed case as historical proof.

The API logs only per-check PASS/FAIL/NOT_CHECKED, a fixed failure code, UTC timestamp, path/status and a generated trace ID. It never logs token/Authorization values, claims, request body or document content. CSIT reports HTTP status and X-CSIT-Auth-Trace for correlation, optionally sanitized claims. No new diagnostic endpoint or ingestion job is created. The API image is km-csit-integration:v1-direct-auth-probe-20261012; 168 isolated integration/binding tests passed, including all previous 156. The worker image remains unchanged and stopped.

## 2026-10-13 canonical number contract repair

Overall：FAIL（fresh CSIT safe probe 尚未執行）
422 Reproduced：YES（原 deployed validator 的純 schema 重現）
Exact Validation Error：project.code / case.code / task.code → missing / Field required；project.number / case.number / task.number → extra_forbidden / Extra inputs are not permitted
expected：舊 validator 要求必填 code:string(1–256)，並禁止 number
received：canonical 重現缺少 code，提供 number:string；歷史 request body 未保留
Root Cause Owner：KM
Exact Root Cause：Reference 的公開欄位誤寫 code，偏離核定 id/number/name 契約
KM Validator Before：id/code/name 必填，extra=forbid
Canonical Contract：id/number/name 必填
Fix Applied：必填 number；修正 repository/Qdrant 映射；保留嚴格型別/limits/forbid；新增不含 input 值的 schema trace
Validation Loosened：NO
Safe Contract Probe：FAIL（未執行正式 fresh-token probe；isolated signed fixture test PASS）
Safe Probe HTTP：N/A（isolated 503 已 PASS；正式期望 503）
Authentication：PASS（使用者已確認正式 422 request；本輪 fresh probe 待執行）
Schema Validation：PASS（實際 deployed model 對 canonical shape；正式 HTTP probe 待執行）
Job Count Before：0
Job Count After：0
Job Created：NO
Integration Tests：175 passed（另 Human OIDC7 / Binding23，共205 passed）
Human OIDC：PASS
TEST / DA40 / RD2：PASS
KM_CSIT_ENABLED：false
Worker：OFF
v3 Retried：NO
CSIT Modified：NO
Production Modified：NO
commit/push：NO / NO
Remaining Blocker：由 CSIT runtime 發送 fresh valid service-token + canonical contract-valid safe probe；KM 端核對正式 HTTP503/schemaPASS與 jobs0→0 後才能標記 READY FOR FINAL v3 RETRY。

Only number is accepted for project/case/task public references; existing *_code storage fields receive the number value. No schema migration or writer-data change. Auth/config unchanged. Evidence: protected csit-contract-422-20261013; runtime API healthy, enabledfalse/workerOFF/jobs0. Original body/error not retained; six code-missing/number-extra errors are validation-only reproduction, not recovered historical request. Fresh real CSIT safe probe remains pending, must reach503 with zero jobs before finalv3retry.
