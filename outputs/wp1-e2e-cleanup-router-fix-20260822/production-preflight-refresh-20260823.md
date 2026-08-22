# Production Preflight Refresh

Date: 2026-08-23 (Asia/Taipei)

This is a read-only preflight. Production was not restarted, deployed, written,
migrated, restored, or used for real-instrument activity.

## Candidate

- Source: `e8455db7f36398995c0ec51647aff21aa4df3925`
- Release: `wp1-e2e-cleanup-router-fix-20260822-r1`
- Image: `sha256:f3290d5d594d20aa35e2b3799675f86a9dc615a01063acfa9efd8097bc710cf0`
- Candidate image exists locally and matches PR #14 evidence.

## Current Runtime and Checkpoint

- Current production web image: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Checkpoint: `/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946`
- Checkpoint SHA-256: `18f0f3ff7f5652ad72b45d8ddc497ef8f7ece34b2de9a822ed7436fe0d719d3f`
- Checkpoint verification: PASS; 23 checksum files verified.
- Rollback target matches current runtime: `true`
- Rollback readiness: `PASS`
- Drift since checkpoint: `false` based on read-only identity, health, queue, and checkpoint checks; no unauthorized change was observed.

All five application images (`web`, search worker, ingest worker, beat, nginx)
matched their checkpoint image IDs. Health, WP0/WP1 runtime gates, Celery two-node
ping, and all inspected queues passed; queues were empty.

## Gate

Production Gate remains `NO-GO_PENDING_SUPERVISOR_DEPLOYMENT_GO`. The current
production `/api/v1/version` returned HTTP 200 with legacy `commit=null`; this
does not identify the new candidate and is not treated as candidate evidence.

Approved rollback command, not executed in this preflight:

```text
python3 scripts/rollback_pre_wp01.py --checkpoint /home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946 --execute --confirm-production PRE_WP01_ROLLBACK
```
