# WP1 Production Preflight Refresh

## Result

This was a read-only preflight. **Production Gate remains `NO-GO`.** No
restart, deployment, write, migration, restore, WP2 work, or real-instrument
operation was performed.

## Current production

- Web image: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Health: PASS
- WP0/WP1 runtime gates: PASS
- Celery: 2 nodes
- Active/reserved/scheduled tasks: 0/0/0
- Inspected queues: all 0

## Rollback baseline

- Checkpoint: `/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946`
- Checkpoint SHA-256: `18f0f3ff7f5652ad72b45d8ddc497ef8f7ece34b2de9a822ed7436fe0d719d3f`
- Verification: PASS, 23 checksum files verified
- Rollback target: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Target matches current runtime: `true`
- Rollback readiness: PASS
- Drift since checkpoint: false

## PR #15 candidate

- Source: `4042284c23f2076e16a476f2426ec1f1ca73f7b4`
- Release: `wp1-job-lease-startup-fix-20260824`
- Image: `sha256:ed09a772cae7ddcb8251dac59f4e1921e6da24642bb4b7708b912edd97db2ea6`
- Candidate exists locally and is not the old `f3290...` image.

## Planned deployment configuration

The rendered Compose plan explicitly sets:
`KB_JOB_LEDGER_PATH=/home/da40_ai_gb10/knowledge-base/data/job-ledger.sqlite3`
for `web`, `celery_search_worker`, `celery_ingest_worker`, and `celery_beat`.
All four use the same image and shared data mount. Web remains configured for
four Uvicorn workers. The startup lock is adjacent to the database:
`/home/da40_ai_gb10/knowledge-base/data/.job-ledger.sqlite3.init.lock`.
The plan does not rely on the application fallback path.

## Temporary E2E identity

The previously reviewed additive provisioning procedure remains planned:
preserve the existing registry, use a 0600 runtime env, exclude secrets from
evidence, remove the temporary identity after acceptance, verify post-removal
authentication rejection, and retain rollback safety.

## CI and recommendation

- [WP0 CI 32669829674](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/32669829674): PASS
- [WP1 CI 32669831189](https://github.com/kyocarlos/knowledge-base-agent-source/actions/runs/32669831189): PASS

The read-only preflight is PASS and can be submitted for supervisor Production
GO Review. It is not deployment authorization.
