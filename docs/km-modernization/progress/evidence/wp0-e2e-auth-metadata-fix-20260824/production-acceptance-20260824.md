# WP0 Production Acceptance Evidence

## Result

The approved candidate was deployed with an exact digest and the controlled synthetic write flow completed. The result is recorded as **PASS WITH BROWSER TOOLING GAP**, not as final WP0 closure.

Candidate: `2ef93d6b47d05b1acbc05fadc0df8393fefd41a0` / `wp0-e2e-auth-metadata-fix-20260824-r1` / `sha256:18039a96b063b3fd85d7c40b975b323f25de71b169efcd9a7d20c2f0f7a5a749`.

## Deployment And Identity

- Only `web`, search worker, ingest worker and beat were recreated.
- All four services ran the exact candidate image and reported identical release metadata.
- `/api/v1/version` returned HTTP 200 with the exact source, release, image digest and RFC3339 build timestamp.
- All four services used `/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3`.
- The persistent read-only frontend mount remained `/home/da40_ai_gb10/knowledge-base/.frontend-build-runtime-user8` to `/usr/share/nginx/html`.

## Acceptance

Synthetic run `TR-E2E-WP0-PROD-20260824-180658-5688b9d2-retry1` used synthetic-only data. Upload returned 202, duplicate upload returned 202 with the same submission, approval returned 200, and ingest reached `completed`. Cleanup dry-run and apply returned 200; the submission returned 404 after cleanup and residual count was 0. Health, WP0/WP1 runtime gates, Celery (2 nodes), queue state and the legacy WebSocket proxy gate were PASS.

The temporary identity was removed. Existing registry entries were preserved; regular authentication remained fail-closed (401 without credentials and 403 with the removed identity), and E2E write mode was disabled after cleanup.

## Rollback

Rollback was not required. Readiness was PASS against checkpoint `outputs/current-runtime-checkpoints/pre-deploy-wp0-e2e-auth-metadata-20260824-1801`; its SHA256SUMS digest is recorded in the JSON evidence. No migration, restore, WP2 deployment or real-instrument access occurred.

## Evidence Gap

The host Chromium snap could not start because its runtime attempted writes in read-only paths. Therefore post-deployment Playwright visual inspection and browser-level console/network capture were not completed. Static HTTP route and asset checks passed, and the existing `restart_kb.sh --status` WebSocket proxy gate passed. A writable supported browser runtime is required before a supervisor can treat the browser evidence item as closed.

WP0 remains **94% Owner Accepted**. W34 and PPTX were intentionally not changed.
