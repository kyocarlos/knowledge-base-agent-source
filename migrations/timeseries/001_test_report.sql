-- KM-TS-REPORT-V1.  Apply with a migration role, never from an API request.
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS test_run (
    run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    document_version TEXT NOT NULL,
    revision TEXT NOT NULL DEFAULT '1',
    package_id TEXT,
    report_id TEXT,
    source_file_name TEXT NOT NULL,
    source_file_sha256 TEXT NOT NULL,
    project_code TEXT NOT NULL,
    dut_model TEXT NOT NULL,
    firmware TEXT,
    test_case TEXT,
    band TEXT,
    direction TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    overall_verdict TEXT NOT NULL,
    publish_status TEXT NOT NULL DEFAULT 'draft',
    is_current BOOLEAN NOT NULL DEFAULT FALSE,
    acl JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_locator JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, document_version),
    CONSTRAINT test_run_verdict CHECK (overall_verdict IN ('pass', 'fail', 'error', 'skipped'))
);

CREATE TABLE IF NOT EXISTS metric_sample (
    observed_at TIMESTAMPTZ NOT NULL,
    sample_key TEXT NOT NULL,
    run_id TEXT NOT NULL,
    document_version TEXT NOT NULL,
    case_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    unit TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    raw_unit TEXT NOT NULL,
    sequence_key TEXT NOT NULL DEFAULT '',
    dimensions JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_locator JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (observed_at, sample_key),
    CONSTRAINT metric_sample_finite CHECK (value = value AND value NOT IN ('Infinity'::double precision, '-Infinity'::double precision))
);
SELECT create_hypertable('metric_sample', 'observed_at', if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS test_run_summary (
    run_id TEXT NOT NULL,
    document_version TEXT NOT NULL,
    case_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    unit TEXT NOT NULL,
    min_value DOUBLE PRECISION NOT NULL,
    max_value DOUBLE PRECISION NOT NULL,
    avg_value DOUBLE PRECISION NOT NULL,
    sample_count BIGINT NOT NULL,
    source_locator JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, document_version, case_id, metric_name, unit)
);

CREATE INDEX IF NOT EXISTS test_run_project_current_idx
    ON test_run (project_code, is_current, publish_status, started_at DESC);
CREATE INDEX IF NOT EXISTS metric_sample_lookup_idx
    ON metric_sample (run_id, document_version, metric_name, observed_at DESC);
CREATE INDEX IF NOT EXISTS summary_lookup_idx
    ON test_run_summary (run_id, document_version, metric_name);

COMMENT ON TABLE test_run IS 'KM test report identity and provenance; source approval remains upstream.';
COMMENT ON TABLE metric_sample IS 'Time-series samples extracted from validated test reports.';
COMMENT ON TABLE test_run_summary IS 'Deterministic summaries computed from metric_sample rows.';
