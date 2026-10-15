-- Apply in the KM Timescale management/deployment phase before web or ingest runtime.
-- Existing DEV rows remain untouched; do not run this with the runtime app role.
BEGIN;
CREATE TABLE IF NOT EXISTS public.km_ui_uploads (
    task_id text PRIMARY KEY,
    data_zone text NOT NULL,
    file_name text NOT NULL,
    file_hash char(64) NOT NULL,
    extraction_mode text NOT NULL,
    status text NOT NULL,
    run_id text,
    uploaded_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.km_ui_report_measurements (
    data_zone text NOT NULL,
    run_id text NOT NULL,
    case_id text NOT NULL,
    metric text NOT NULL,
    sample_index integer NOT NULL,
    value double precision NOT NULL,
    unit text NOT NULL,
    started_at timestamptz NOT NULL,
    task_id text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (data_zone, run_id, case_id, metric, sample_index)
);
COMMIT;
