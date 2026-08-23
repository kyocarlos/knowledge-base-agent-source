# fix: mount isolated E2E cleanup router

## Scope

This is an independent fix cycle after PR #13's write smoke found that the
existing cleanup route module was not mounted. The change adds only the
existing `e2e_cleanup_routes` router to the FastAPI application. Search and
metadata implementations are unchanged.

## Candidate

- Fix source: `e8455db7f36398995c0ec51647aff21aa4df3925`
- Evidence commit: `ad78fbe3569ebba95e1f07e9eeaa5139839f19c3`
- Release: `wp1-e2e-cleanup-router-fix-20260822-r1`
- Image: `sha256:f3290d5d594d20aa35e2b3799675f86a9dc615a01063acfa9efd8097bc710cf0`
- Build timestamp: `2026-08-22T23:32:27+08:00`

## Isolated Smoke

Synthetic run `TR-E2E-WP1-CLEANUP-FIX-20260822-234514-bf02b7bd` passed:

- Health and Search
- Report API agent self-read
- Shared job ledger
- Upload/Ingest completion
- Duplicate submission deduplication
- Report approve/read
- Worker completion
- Cleanup dry-run/apply
- Post-cleanup Health
- Residual count 0

Additional same-image shadow evidence passed worker recovery, in-flight
redelivery, application idempotency and Redis reconnect/SETNX idempotency.

Production was not touched. No production deployment, write, migration,
destructive restore, WP2 or real instrument action was performed.

## Gate

- Production Gate: `NO-GO`
- PR #12 and PR #13 remain Draft.
- This PR is Draft and must not be merged before supervisor review.

Evidence:

- `outputs/wp1-e2e-cleanup-router-fix-20260822/controlled-write-smoke.json`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/summary.json`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/summary.md`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/production-preflight-refresh-20260823.json`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/production-preflight-refresh-20260823.md`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/production-acceptance-attempt-20260823.json`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/production-acceptance-attempt-20260823.md`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/temporary-e2e-agent-provisioning-shadow-20260823.json`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/temporary-e2e-agent-provisioning-shadow-20260823.md`

## CI

- WP0 exact-head CI: [run 32582751280](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/32582751280) — success
- WP1 exact-head CI: [run 32582753347](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/32582753347) — success
- Preflight evidence head WP0 CI: [run 32583563574](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/32583563574) — success
- Preflight evidence head WP1 CI: [run 32583564639](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/32583564639) — success
- Temporary provisioning evidence head WP0 CI: [run 32611312626](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/32611312626) — success
- Temporary provisioning evidence head WP1 CI: [run 32611313646](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/32611313646) — success

## Production Preflight Refresh (2026-08-23)

- Current production web image: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Checkpoint: `/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946`
- Checkpoint SHA-256: `18f0f3ff7f5652ad72b45d8ddc497ef8f7ece34b2de9a822ed7436fe0d719d3f`
- Checkpoint verification: PASS; rollback target matches current runtime; rollback readiness PASS
- All five application image identities match the checkpoint; Health/WP0/WP1 gates PASS
- Celery: 2 nodes; inspected queues empty; no observed drift since checkpoint
- Candidate image exists locally and matches the candidate identity above
- Production Gate remains `NO-GO`; no deployment, restart, write, migration, restore or real-instrument action was performed

## Production Acceptance Attempt (2026-08-23)

- Identity gate: PASS
- Synthetic run: `TR-E2E-WP1-PROD-20260823-093524-unique`
- Health/Search/report agent health/upload/duplicate dedup: PASS
- Report self-read: FAIL HTTP 403
- Root cause classification: production configuration; the temporary E2E agent identity was not present in the regular agent registry used by self-read.
- Synthetic cleanup: PASS; residual count 0
- Approved rollback: PASS; final runtime returned to `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Production acceptance: FAIL; Production Gate: `NO-GO`
- No source code was modified during the attempt. Retry requires separately approved E2E agent-registry configuration.

## Temporary E2E Agent Provisioning Shadow Review

- Shadow result: PASS
- Method: additive runtime JSON merge in a temporary mode `0600` env, followed by controlled application-service restart
- Existing regular registry: preserved; 2 entries retained
- Temporary identity: authenticated while provisioned and was rejected after removal
- Secrets in evidence: false
- Removal procedure and rollback safety: defined and PASS
- Production provisioning/deployment in this shadow step: not performed

## Production Acceptance Retry (2026-08-23)

Supervisor-approved additive temporary provisioning was used for a new
controlled retry. The candidate identity gate passed, but acceptance failed
because the ingest task remained queued after the worker did not acquire its
lease. Report approve/read returned HTTP 409 and cleanup apply correctly
returned HTTP 409 while the task was active/queued. Residual reconciliation is
therefore blocked and must not be reported as zero.

- Run ID: `TR-E2E-WP1-PROD-RETRY-20260823-095504-unique`
- Temporary provisioning: additive; 2 existing regular registry entries preserved; mode 0600; secrets excluded
- Health/Search/agent health/upload/duplicate dedup/report self-read: PASS
- Report approve/read: FAIL HTTP 409 (`queued`)
- Worker completion: blocked by lease; task `ingest_20260823_015605_be828d38`
- Cleanup dry-run: PASS; cleanup apply: FAIL HTTP 409 active task; residual reconciliation: BLOCKED
- Temporary identity removal: PASS; post-removal authentication rejected HTTP 403
- Rollback: PASS to the approved current-production baseline
- Final Health: HTTP 200; Celery: 2 nodes; queues: empty
- Production Gate: `NO-GO`; no source code was changed

Evidence:

- `outputs/wp1-e2e-cleanup-router-fix-20260822/production-acceptance-retry-20260823.json`
- `outputs/wp1-e2e-cleanup-router-fix-20260822/production-acceptance-retry-20260823.md`

The next blocker is a separately reviewed production ingest lease/task-state
reconciliation and cleanup completion issue. Do not retry production or alter
the candidate until approved.
