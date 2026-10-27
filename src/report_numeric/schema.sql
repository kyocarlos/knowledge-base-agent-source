-- km_test: numeric store for test reports (KM v2.6). Regular tables inside the TimescaleDB instance: reports have discrete
-- measurements without per-second timestamps, so no hypertable. Re-runnable (IF NOT EXISTS); rollback = DROP SCHEMA km_test CASCADE.
CREATE SCHEMA IF NOT EXISTS km_test;

CREATE TABLE IF NOT EXISTS km_test.metric_dictionary (
  metric_name        text PRIMARY KEY,
  unit               text NOT NULL,
  kind               text NOT NULL CHECK (kind IN ('measured','reported_derived')),
  higher_is_better   boolean,                 -- NULL = undefined: comparisons must not say better/worse
  plausible_min      double precision,
  plausible_max      double precision,
  description        text,
  UNIQUE (metric_name, unit)
);

CREATE TABLE IF NOT EXISTS km_test.test_run (
  test_run_id        text PRIMARY KEY,
  id_basis           text NOT NULL CHECK (id_basis IN ('derived','csit','automation')),
  csit_id            text,
  report_id          text NOT NULL,
  document_id        text NOT NULL,
  document_version   text NOT NULL,
  report_revision    integer,
  report_type        text NOT NULL,
  technology         text NOT NULL,
  product_id         text NOT NULL,
  product_id_basis   text NOT NULL CHECK (product_id_basis IN ('derived','csit')),
  dut_model          text NOT NULL,
  npi_stage          text,
  firmware_id        text,
  firmware_version   text,
  hardware_version   text,
  chipset_vendor     text,
  ethernet_type      text,
  test_date          date,
  overall_result     text CHECK (overall_result IN ('pass','fail','n/a','error','skipped')),
  source_system      text NOT NULL,
  source_record_id   text,
  approval_status    text NOT NULL,
  approval_basis     text NOT NULL CHECK (approval_basis IN ('assumed_manual','csit')),
  publish_status     text NOT NULL,
  is_current         boolean NOT NULL DEFAULT true,
  project_id         text,
  owner_department   text,
  visibility         text NOT NULL CHECK (visibility IN ('internal','department','private')),
  access_roles       text[] NOT NULL DEFAULT '{}',
  access_departments text[] NOT NULL DEFAULT '{}',
  quality_status     text NOT NULL CHECK (quality_status IN ('clean','source_errors_accepted')),
  formula_error_count integer NOT NULL DEFAULT 0,
  package_id         text NOT NULL,
  schema_version     text NOT NULL,
  content_hash       text NOT NULL,
  ingested_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, document_version)
);
CREATE INDEX IF NOT EXISTS test_run_product_idx ON km_test.test_run (product_id, firmware_id);
CREATE INDEX IF NOT EXISTS test_run_type_idx    ON km_test.test_run (report_type, technology);

CREATE TABLE IF NOT EXISTS km_test.test_measurement (
  measurement_id     uuid PRIMARY KEY,
  test_run_id        text NOT NULL REFERENCES km_test.test_run (test_run_id) ON DELETE CASCADE,
  test_case_id       text NOT NULL,
  test_case_name     text,
  metric_name        text NOT NULL,
  value              double precision NOT NULL,
  unit               text NOT NULL,
  value_basis        text NOT NULL CHECK (value_basis IN ('measured','reported_derived','recomputed')),
  band               text,
  bandwidth_mhz      integer,
  channel            integer,
  center_freq_mhz    integer,
  direction          text CHECK (direction IN ('dl','ul','total')),
  direction_source_label text,
  attenuation_db     double precision,
  angle_deg          double precision,
  traffic_mode       text CHECK (traffic_mode IN ('unidirectional','bidirectional')),
  protocol           text CHECK (protocol IN ('tcp','udp')),
  statistic          text CHECK (statistic IN ('value','peak','average','min','max')),
  sample_index       integer,
  time_slot          text,
  wireless_mode      text,
  source_sheet       text NOT NULL,
  source_cell_range  text NOT NULL,
  FOREIGN KEY (metric_name, unit) REFERENCES km_test.metric_dictionary (metric_name, unit),
  UNIQUE NULLS NOT DISTINCT (test_run_id, test_case_id, metric_name, direction, band, bandwidth_mhz, channel, attenuation_db, angle_deg,
                             traffic_mode, protocol, statistic, sample_index, value_basis)
);
CREATE INDEX IF NOT EXISTS test_measurement_cmp_idx ON km_test.test_measurement (metric_name, band, bandwidth_mhz, channel, direction);
CREATE INDEX IF NOT EXISTS test_measurement_run_idx ON km_test.test_measurement (test_run_id);

CREATE TABLE IF NOT EXISTS km_test.test_item_result (
  result_id          uuid PRIMARY KEY,
  test_run_id        text NOT NULL REFERENCES km_test.test_run (test_run_id) ON DELETE CASCADE,
  test_case_id       text NOT NULL,
  item_label         text NOT NULL,
  band               text,
  bandwidth_mhz      integer,
  channel            integer,
  criteria_value     double precision,
  criteria_unit      text,
  criteria_basis     text,
  result             text NOT NULL CHECK (result IN ('pass','fail','n/a','error','skipped')),
  result_basis       text NOT NULL CHECK (result_basis IN ('report','recomputed')),
  source_sheet       text NOT NULL,
  source_cell_range  text NOT NULL,
  UNIQUE (test_run_id, test_case_id, item_label)
);
CREATE INDEX IF NOT EXISTS test_item_result_idx ON km_test.test_item_result (test_run_id, result);

CREATE TABLE IF NOT EXISTS km_test.criteria_reference (
  criteria_id        uuid PRIMARY KEY,
  test_run_id        text NOT NULL REFERENCES km_test.test_run (test_run_id) ON DELETE CASCADE,
  band               text,
  bandwidth_mhz      integer,
  spatial_stream     text,
  wireless_mode      text,
  attenuation_range  text,
  reference_rate_mbps double precision,
  criteria_value     double precision,
  criteria_unit      text,
  criteria_basis     text,
  source_sheet       text NOT NULL,
  source_cell_range  text NOT NULL
);

CREATE TABLE IF NOT EXISTS km_test.test_condition (
  condition_id       uuid PRIMARY KEY,
  test_run_id        text NOT NULL REFERENCES km_test.test_run (test_run_id) ON DELETE CASCADE,
  name               text NOT NULL,
  value              double precision,
  text_value         text,
  unit               text,
  band               text,
  bandwidth_mhz      integer,
  source_sheet       text NOT NULL,
  source_cell_range  text NOT NULL
);

CREATE TABLE IF NOT EXISTS km_test.report_package (
  package_id         text PRIMARY KEY,
  document_id        text NOT NULL,
  document_version   text NOT NULL,
  test_run_id        text NOT NULL,
  content_hash       text NOT NULL,
  quality            jsonb NOT NULL,
  ingested_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (document_id, document_version)
);
