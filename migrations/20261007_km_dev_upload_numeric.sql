-- Apply only to approved KM DEV Timescale DB via management channel.
-- Stable source/version/point identity makes replay and partial failure safe.
BEGIN;
CREATE SCHEMA IF NOT EXISTS km_dev_upload;
SET LOCAL search_path TO km_dev_upload, public;
CREATE TABLE IF NOT EXISTS km_csit_numeric_points (
 point_id uuid NOT NULL, source_system text NOT NULL CHECK(source_system='KM_DEV_UPLOAD'),
 document_id text NOT NULL, version integer NOT NULL, observed_at timestamptz NOT NULL,
 metric text NOT NULL, value double precision NOT NULL, unit text NOT NULL,
 lineage jsonb NOT NULL, PRIMARY KEY(observed_at, point_id)
);
SELECT public.create_hypertable('km_dev_upload.km_csit_numeric_points','observed_at',if_not_exists=>TRUE);
COMMIT;
