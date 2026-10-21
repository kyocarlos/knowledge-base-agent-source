-- KM DEV Control PostgreSQL; explicit management-channel migration.
-- Runtime initialization MUST NOT execute DDL. No existing auth tables are changed.
BEGIN;
CREATE TABLE IF NOT EXISTS km_csit_ingestion_jobs (
 job_id uuid PRIMARY KEY,
 event_id text NOT NULL,
 source_system text NOT NULL CHECK(source_system='CSIT'),
 event_type text NOT NULL CHECK(event_type='TestReportCommitted'),
 document_id text NOT NULL,
 version integer NOT NULL CHECK(version>0),
 project_id text NOT NULL, project_code text NOT NULL, project_name text NOT NULL,
 case_id text NOT NULL, case_code text NOT NULL, case_name text NOT NULL,
 task_id text NOT NULL, task_code text NOT NULL, task_name text NOT NULL,
 file_name text NOT NULL, content_type text NOT NULL, size_bytes bigint NOT NULL CHECK(size_bytes>=0),
 committed_at timestamptz NOT NULL, request_payload jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('Accepted','Processing','Completed','Failed')),
 phase text NOT NULL DEFAULT 'Accepted',
 attempt_count integer NOT NULL DEFAULT 0,
 download_attempt_count integer NOT NULL DEFAULT 0,
 next_retry_at timestamptz,
 last_error_code text, last_error_message text, last_error_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 started_at timestamptz, completed_at timestamptz,
 lease_token uuid, lease_until timestamptz, worker_id text,
 content_sha256 text,
 parser_version text, extraction_version text,
 storage_references jsonb NOT NULL DEFAULT '{}',
 processing_duration_ms bigint,
 UNIQUE(source_system,document_id,version)
);
CREATE INDEX IF NOT EXISTS km_csit_jobs_ready ON km_csit_ingestion_jobs(status,next_retry_at,lease_until);
CREATE TABLE IF NOT EXISTS km_csit_phase_checkpoints (
 job_id uuid NOT NULL REFERENCES km_csit_ingestion_jobs(job_id),
 phase text NOT NULL, result jsonb NOT NULL,
 completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(job_id,phase)
);
CREATE TABLE IF NOT EXISTS km_csit_callback_deliveries (
 delivery_id uuid PRIMARY KEY,
 job_id uuid NOT NULL REFERENCES km_csit_ingestion_jobs(job_id),
 payload jsonb NOT NULL, sequence bigint GENERATED ALWAYS AS IDENTITY,
 status text NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Delivering','Delivered','Failed')),
 attempt_count integer NOT NULL DEFAULT 0, next_retry_at timestamptz,
 last_error_code text, last_error_at timestamptz,
 lease_token uuid, lease_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), delivered_at timestamptz
);
CREATE INDEX IF NOT EXISTS km_csit_callbacks_ready ON km_csit_callback_deliveries(status,next_retry_at,lease_until);
COMMIT;
