-- KM DEV Control PostgreSQL; explicit management-channel migration (CSIT x AI KM spec v1.3).
-- Document-library ingestion, document deletion and tombstones. Test Report v1 tables are not changed.
-- Runtime initialization MUST NOT execute DDL.
BEGIN;
CREATE SEQUENCE IF NOT EXISTS km_csit_doclib_job_seq;
CREATE SEQUENCE IF NOT EXISTS km_csit_deletion_job_seq;

CREATE TABLE IF NOT EXISTS km_csit_doclib_jobs (
 csit_job_id uuid PRIMARY KEY,
 km_job_id text NOT NULL UNIQUE,
 document_file_id uuid NOT NULL,
 request_payload jsonb NOT NULL,
 original_file_name text NOT NULL, standard_file_name text,
 content_type text NOT NULL, file_size_bytes bigint NOT NULL CHECK(file_size_bytes>=0),
 expected_sha256 text NOT NULL CHECK(expected_sha256 ~ '^[0-9a-f]{64}$'),
 occurred_at timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('Accepted','Processing','Completed','Failed','Cancelled','Deleted')),
 phase text NOT NULL DEFAULT 'Accepted',
 attempt_count integer NOT NULL DEFAULT 0,
 next_retry_at timestamptz,
 last_error_code text, last_error_message text, last_error_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 started_at timestamptz, completed_at timestamptz, failed_at timestamptz,
 lease_token uuid, lease_until timestamptz, worker_id text,
 content_sha256 text,
 result_json jsonb,
 storage_references jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS km_csit_doclib_jobs_ready ON km_csit_doclib_jobs(status,next_retry_at,lease_until);
CREATE INDEX IF NOT EXISTS km_csit_doclib_jobs_file ON km_csit_doclib_jobs(document_file_id);

CREATE TABLE IF NOT EXISTS km_csit_doclib_checkpoints (
 csit_job_id uuid NOT NULL REFERENCES km_csit_doclib_jobs(csit_job_id),
 phase text NOT NULL, result jsonb NOT NULL,
 completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(csit_job_id,phase)
);

CREATE TABLE IF NOT EXISTS km_csit_deletion_jobs (
 deletion_request_id uuid PRIMARY KEY,
 km_deletion_job_id text NOT NULL UNIQUE,
 request_payload jsonb NOT NULL,
 reason_code text NOT NULL,
 source_type text NOT NULL CHECK(source_type IN ('DocumentLibraryFile','TestReport','VerificationApplicationAttachment')),
 source_key text NOT NULL,
 resource jsonb NOT NULL,
 requested_at timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('Accepted','Processing','Completed','Failed')),
 phase text NOT NULL DEFAULT 'Accepted',
 attempt_count integer NOT NULL DEFAULT 0,
 next_retry_at timestamptz,
 last_error_code text, last_error_message text, last_error_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 started_at timestamptz, completed_at timestamptz, failed_at timestamptz,
 lease_token uuid, lease_until timestamptz, worker_id text,
 cleanup_result jsonb
);
CREATE INDEX IF NOT EXISTS km_csit_deletion_jobs_ready ON km_csit_deletion_jobs(status,next_retry_at,lease_until);

-- A tombstone outlives the deleted data: late ingestion, retries and callbacks must not resurrect the source.
CREATE TABLE IF NOT EXISTS km_csit_tombstones (
 source_type text NOT NULL,
 source_key text NOT NULL,
 deletion_request_id uuid NOT NULL,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(source_type,source_key)
);

-- One ordered outbox for both ingestion and deletion callbacks.
CREATE TABLE IF NOT EXISTS km_csit_v13_callbacks (
 callback_id uuid PRIMARY KEY,
 kind text NOT NULL CHECK(kind IN ('ingestion','deletion')),
 ref_id text NOT NULL,
 payload jsonb NOT NULL,
 sequence bigint GENERATED ALWAYS AS IDENTITY,
 status text NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Delivering','Delivered','Failed')),
 attempt_count integer NOT NULL DEFAULT 0, next_retry_at timestamptz,
 last_error_code text, last_error_at timestamptz,
 lease_token uuid, lease_until timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(), delivered_at timestamptz
);
CREATE INDEX IF NOT EXISTS km_csit_v13_callbacks_ready ON km_csit_v13_callbacks(status,next_retry_at,lease_until);
COMMIT;
