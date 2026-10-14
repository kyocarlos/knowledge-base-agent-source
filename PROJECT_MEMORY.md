# KM DEV developer handoff memory

Baseline date: 2026-10-14. Branch: codex/km-dev-handoff-20261014.
Read README.md and docs/handoff/PATTY_DEVELOPMENT_HANDOFF.md first.
Source comes from the latest DGX first-party working tree plus deployed DEV Control source; source-origins.json and source-manifest.json provide hashes and provenance.
Focused integration/Human OIDC/binding suite: 240 passed in the new public-base test build. Disabled API sandbox rebuilt from an empty database: health ok, integrationEnabled=false, worker not started.
Processing timestamps.startedAt fix is included in this source; it remains undeployed in the existing DGX runtime. Failed timestamps.failedAt stays a separately authorized follow-up.
Existing live same-v3 job is Completed; preserve historical callback failures and never re-resume or resend it to validate new source.
This branch contains no live credentials, runtime data or model cache. Build/development readiness is not Production release or whole Phase 1 acceptance. Read validation.json for exact build/test coverage.
The original DGX working tree/runtime was not changed by this isolated handoff. Credentials are supplied through external protected files, never committed.

## 2026-10-14 canonical contract adoption source checkpoint

User authorized the exact CSIT-System commit 3a9ae52f04625aeee5fd01e7a3565f5972fc9122 as the only current Integration v1 wire authority, requested all listed drift fixes, KM DEV deployment, deployed-runtime deterministic offline verification, integration disabled, and no new Live E2E. Remote identity spark-7546/da40_ai_gb10 and clean branch baseline b3aa002556c7905e3d91691420dbcdc7b7f19ba1 were confirmed. No password is retained.

Four exact schemas were fetched from the pinned raw commit; SHA-256/byte parity passed. Source now uses UUID types, required nullable reference number/name, positive sizeBytes, a single production callback builder with Failed.failedAt=last_error_at, a six-column nullable migration, principal_type=service defaults, a canonical schema test suite, valid UUID fixtures, legacy/current contract labels, push-triggered CI gate, and an offline verifier module packaged into the API image. Final complete isolated suite passed 261 tests plus the packaged offline verifier. The real DEV API is still the old image sha256:396b9c03... with KM_CSIT_ENABLED=false and healthy; worker image sha256:da1178eb... is OFF. Real KM Control DB public.km_csit_ingestion_jobs has one Completed job; six lineage columns are NOT NULL. No new job, callback, Live E2E, or DEV deployment has occurred yet. Next: source commit/push/CI, then controlled DB migration/API+stopped worker image deployment with rollback evidence and actual runtime offline verification.
