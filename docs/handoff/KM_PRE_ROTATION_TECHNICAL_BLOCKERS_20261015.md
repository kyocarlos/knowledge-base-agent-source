# KM DEV pre-rotation technical blocker removal (2026-10-15)

## Scope and result

This change removes TimescaleDB schema provisioning from the normal KM web and ingest upload-tracking path. It does not rotate a credential, start CSIT ingestion, or access Production. The approved CSIT canonical wire contract remains commit `3a9ae52f04625aeee5fd01e7a3565f5972fc9122`; deployed CSIT API/worker source remains `45108b1fb4a4672945d99238080f75069929f2ec`.

## Exact Timescale runtime DDL call sites

| Source and function | Caller/service | Trigger | Object | Class/disposition |
| --- | --- | --- | --- | --- |
| `src/ui_upload_tracking.py`, `record_upload`, old `CREATE TABLE IF NOT EXISTS km_ui_uploads` | `src/web_api/__init__.py`, normal upload request; web | Every accepted upload | `public.km_ui_uploads` | B: moved to `migrations/20261015_km_ui_upload_tracking.sql` |
| `src/ui_upload_tracking.py`, `record_upload`, old `CREATE TABLE IF NOT EXISTS km_ui_report_measurements` | `src/web_api/tasks.py`, extraction result; ingest Celery | Successful ingest result | `public.km_ui_report_measurements` | B: moved to same migration |
| `src/csit_integration_v1/writers.py`, `TimescaleWriter.write` | CSIT worker | Numeric point write | `public.km_csit_numeric_points` | No DDL: INSERT/ON CONFLICT UPDATE only. Existing migration: `migrations/20261007_csit_numeric_v1.sql`. |

The web and ingest services package the same `src/ui_upload_tracking.py` module. Both derivative DEV images contain the patched module. The migration contains the two deterministic, idempotent `CREATE TABLE IF NOT EXISTS` statements; runtime DML uses qualified `public` names. No Timescale runtime `CREATE SCHEMA`, `ALTER TABLE`, `CREATE INDEX`, `create_hypertable`, DROP, or SUPERUSER operation was found in these paths. `migrations/20261007_km_dev_upload_numeric.sql` is an existing management migration.

## Other datastore DDL observed during the wider source inventory

These are not executed with the `kb_timeseries_da40` Timescale credential and are outside this credential rotation's permission cutover. They must not be described as removed by this change:

| Source/function | Normal caller/service | Database and timing | Classification |
| --- | --- | --- | --- |
| `src/ingest_registry.py:IngestRegistry._initialize` | web upload routes; ingest task status/events | SQLite ingestion registry; constructor on requests/tasks; four fixed tables | A, pre-provisioning suitable; separate SQLite lifecycle change needed |
| `src/test_reports/registry.py:SubmissionRegistry._initialize` | report submission routes | report registry PostgreSQL/SQLite; constructor; fixed `report_submissions` table | A, separate registry migration needed |
| `src/km_control.py:ControlRegistry._initialize` | auth/control routes | SQLite fallback only (DEV uses PostgreSQL); six fixed tables and one index | A for SQLite fallback; separate change |
| `src/km_accounts.py:AccountRegistry._initialize` | legacy account registry | PostgreSQL/SQLite; one fixed table | A, separate change if active |
| `src/ingest.py:setup_neo4j_schema`, `src/report_graph.py:setup_report_graph_schema`, `src/graphrag/neo4j_schema.py:setup_neo4j_schema`, `src/test_reports/canonical_graph.py` | normal ingest/report graph paths and graph initialization | Neo4j constraints and indexes | A, separate graph schema deployment phase needed |

No dynamic-object requirement was proven for these fixed objects. Do not use the Timescale least-privilege result to claim that all unrelated datastore service roles are DDL-free.

## Validation

- DEV Timescale before/after object identity, columns, indexes and row counts matched exactly (`km_ui_uploads` 5 rows; `km_ui_report_measurements` 0). Migration applied once to DEV and twice in a disposable isolated Timescale instance; second application was a no-op.
- Disposable runtime role had CONNECT, schema USAGE, SELECT/INSERT/UPDATE; no schema CREATE, DELETE, or SUPERUSER. Actual packaged web, ingest and CSIT writer code completed DML and upsert under that role. A CREATE TABLE attempt failed as expected. No DEV business KPI row was written.
- Focused suite: 283 passed, 2 deselected, 1 warning. One pre-existing OIDC test `test_identity_binding_never_uses_email_or_account_automatically` fails because it calls missing `ControlRegistry.verify_external_identity_local_account`; modified paths do not touch that method. Neo4j integration test was deselected because no isolated Neo4j was provisioned.
- Packaged offline CSIT canonical verifier passed in the deployed API and isolated worker image with integration disabled.
- Normalized semantic reconstruction from Git `deploy/csit-integration-v1/compose.dev.yaml` plus protected external override/env has zero runtime-critical diff for both API and worker. It compares image IDs/revisions, process settings, environment keys/values in memory, mounts, networks, ports, health, restart, user and security settings. No environment values are saved. Raw Compose hash differs and is not used as an acceptance gate.
- DEV web and ingest were recreated with derivative images of their approved existing bases; health and Celery ping passed. CSIT API stayed healthy with `integrationEnabled=false`; CSIT worker remained OFF. No new CSIT job or callback was created.

Protected exact evidence, image pins, command-level cutover and rollback instructions reside under `/home/da40_ai_gb10/.km-control/csit-post-acceptance-freeze-20261015/rotation-execution-package-20261015/` (mode 0700, files 0600). The old credential evidence files remain protected and unchanged. Production scope is UNKNOWN.
