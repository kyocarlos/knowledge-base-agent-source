# WP1 Current Production Maintenance Checkpoint

## Scope

This evidence records the current production runtime immediately before the
planned frozen-release redeployment. It is a read-only checkpoint and rollback
readiness record. No production deployment, restart, write, migration, restore,
or real-instrument access was performed.

## Checkpoint

- Path: `/home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946`
- Created: `2026-08-22T03:09:46.419360+00:00`
- `production_touched`: `false`
- Verifier: `verified=true`
- Checksum files verified: `23`
- `SHA256SUMS` SHA-256: `18f0f3ff7f5652ad72b45d8ddc497ef8f7ece34b2de9a822ed7436fe0d719d3f`

Backup scope includes source state, runtime compose/rollback files,
application image archive, PostgreSQL, Redis, Neo4j, Qdrant, protected runtime
references, nginx certificates, and OpenClaw runtime state.

## Runtime and Rollback Identity

- Current production `kb-web` image: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- Rollback target image: `sha256:a3220ec33ab80c588f289d8560af96c447c6f573da3145fe66ffa2cd719b16ec`
- `rollback_target_matches_current_runtime`: `true`
- Other application image IDs are recorded in the machine-readable JSON next to this file.

Rollback readiness command:

```bash
python3 scripts/rollback_pre_wp01.py \
  --checkpoint /home/da40_ai_gb10/kb-pre-wp01-backups/pre-deploy-current-production-20260822-110946 \
  --execute \
  --confirm-production PRE_WP01_ROLLBACK
```

The non-mutating rollback dry-run passed. The isolated shadow drill passed:
baseline HTTP 200, simulated candidate failure HTTP 503, rollback HTTP 200,
and image identity match. Its evidence is
`outputs/current-production-rollback-drill-20260822.json` with SHA-256
`1d310985329795265b327707b8d14162b4a3d2e7753d2b5f1620e0a95d7fbede`.

## Runtime Health

- Health before checkpoint: HTTP 200, `{"status":"healthy"}`
- Health after checkpoint/drill: HTTP 200, `{"status":"healthy"}`
- Celery nodes: `2`
- Queues: active/reserved/scheduled and search/ingest/default/document/indexing/celery all `0`
- WP0/WP1 status gates: PASS

## Safety Boundary

- `production_write_performed`: `false`
- `migration_performed`: `false`
- `restore_performed`: `false`
- `real_instrument_access`: `false`
- Production Gate: `NO-GO`
- Frozen release source remains `38dda63f4ba53762d926d9874bdf310e3a0eb324`.
