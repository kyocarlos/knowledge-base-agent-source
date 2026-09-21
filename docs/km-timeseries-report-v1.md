# KM-TS-REPORT-V1

This change persists structured measurements from the existing validated Test
Report path. It does not make search counts, LLM calls, or report-page views
create measurement rows.

## Flow

`validated Excel -> existing report parser -> existing ingest/Neo4j/Qdrant -> TimeseriesStore -> summary/query API -> KM report data page`

`metric_sample` is a TimescaleDB hypertable. `test_run` and
`test_run_summary` are ordinary PostgreSQL tables. The source report remains
the authoritative file; TimescaleDB contains structured values and provenance.

## Contract decisions

- `observed_at`, when present, must contain an explicit timezone. Rows without
  a measurement timestamp are retained by the existing report parser but are
  not invented as time-series points; a summary is computed only from actual
  samples.
- Raw value/unit, normalized numeric value/unit, sequence dimensions, and the
  sheet/row locator are retained.
- The first implementation uses deterministic min/max/average/count. P95 and
  interval weighting are not fabricated.
- The API only exposes `published` and `is_current` rows and requires the
  existing KM reviewer bearer token, a project scope, plus `report-reader` or
  `report-admin` role. It fails closed when `KB_REVIEWER_TOKEN_HASHES_JSON` is
  not configured. This is a bounded seam pending the formal CSIT ACL contract.
- Existing CSIT notification receiver, parser, Knowledge Package, lifecycle,
  Qdrant, Neo4j, and worker boundaries remain the integration points.

## Migration

Run `python scripts/apply_timeseries_migrations.py` with a controlled
`KM_TIMESERIES_DATABASE_URL` using a migration-capable account. The API does
not create tables. Destructive downgrade and automatic historical backfill are
out of scope.

## pgAdmin

The Compose delivery includes a localhost-only pgAdmin service. Configure its
secret through the deployment environment and provide a server registration
that uses a read-only database role. The CI Compose project verifies the login,
configured Timescale server, SELECT access, and denied INSERT access. It does
not expose pgAdmin publicly.
