# KM DEV developer handoff memory

Baseline date: 2026-10-14. Branch: codex/km-dev-handoff-20261014.
Read README.md and docs/handoff/PATTY_DEVELOPMENT_HANDOFF.md first.
Source comes from the latest DGX first-party working tree plus deployed DEV Control source; source-origins.json and source-manifest.json provide hashes and provenance.
Focused integration/Human OIDC/binding suite: 240 passed in the new public-base test build. Disabled API sandbox rebuilt from an empty database: health ok, integrationEnabled=false, worker not started.
Processing timestamps.startedAt fix is included in this source; it remains undeployed in the existing DGX runtime. Failed timestamps.failedAt stays a separately authorized follow-up.
Existing live same-v3 job is Completed; preserve historical callback failures and never re-resume or resend it to validate new source.
This branch contains no live credentials, runtime data or model cache. Build/development readiness is not Production release or whole Phase 1 acceptance. Read validation.json for exact build/test coverage.
The original DGX working tree/runtime was not changed by this isolated handoff. Credentials are supplied through external protected files, never committed.
