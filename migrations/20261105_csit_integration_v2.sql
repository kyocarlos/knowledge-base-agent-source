-- KM DEV Control PostgreSQL; explicit management-channel migration (CSIT x AI KM spec v1.4, /v2/ APIs).
-- Additive: v2 document jobs, metadata changes, analysis results; the deletion and callback tables gain v2 values.
-- Runtime initialization MUST NOT execute DDL.
BEGIN;
CREATE SEQUENCE IF NOT EXISTS km_csit_v2_job_seq;
CREATE SEQUENCE IF NOT EXISTS km_csit_v2_change_seq;

CREATE TABLE IF NOT EXISTS km_csit_v2_jobs (
 event_id uuid PRIMARY KEY,
 csit_job_id uuid NOT NULL,
 km_job_id text NOT NULL UNIQUE,
 event_type text NOT NULL,
 source_type text NOT NULL CHECK(source_type IN ('VerificationApplicationAttachment','VendorFile','EquipmentAttachment','TestReport','DocumentLibraryFile')),
 source_entity_id uuid NOT NULL,
 document_id uuid NOT NULL,
 version integer NOT NULL CHECK(version>=1),
 request_payload jsonb NOT NULL,
 original_file_name text NOT NULL,
 content_type text NOT NULL,
 file_size_bytes bigint NOT NULL CHECK(file_size_bytes>0),
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
 storage_references jsonb NOT NULL DEFAULT '{}',
 index_state text NOT NULL DEFAULT 'Pending' CHECK(index_state IN ('Pending','Active','Superseded')),
 superseded_at timestamptz,
 supersede_pending boolean NOT NULL DEFAULT false,
 source_revision integer NOT NULL DEFAULT 0,
 metadata_overrides jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS km_csit_v2_jobs_ready ON km_csit_v2_jobs(status,next_retry_at,lease_until);
CREATE INDEX IF NOT EXISTS km_csit_v2_jobs_source ON km_csit_v2_jobs(source_type,source_entity_id,version);
CREATE INDEX IF NOT EXISTS km_csit_v2_jobs_document ON km_csit_v2_jobs(document_id,version);
-- One active canonical ingestion per (source, version); a Failed or cancelled job may be replaced by a new event.
CREATE UNIQUE INDEX IF NOT EXISTS km_csit_v2_jobs_canonical ON km_csit_v2_jobs(source_type,source_entity_id,version)
 WHERE status IN ('Accepted','Processing','Completed');

CREATE TABLE IF NOT EXISTS km_csit_v2_checkpoints (
 event_id uuid NOT NULL REFERENCES km_csit_v2_jobs(event_id),
 phase text NOT NULL, result jsonb NOT NULL,
 completed_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 PRIMARY KEY(event_id,phase)
);

CREATE TABLE IF NOT EXISTS km_csit_v2_changes (
 change_id uuid PRIMARY KEY,
 km_change_job_id text NOT NULL UNIQUE,
 source_type text NOT NULL,
 source_entity_id uuid NOT NULL,
 document_id uuid NOT NULL,
 version integer NOT NULL CHECK(version>=1),
 source_revision integer NOT NULL CHECK(source_revision>=1),
 request_payload jsonb NOT NULL,
 occurred_at timestamptz NOT NULL,
 status text NOT NULL CHECK(status IN ('Accepted','Processing','Completed','Failed','Cancelled')),
 attempt_count integer NOT NULL DEFAULT 0,
 next_retry_at timestamptz,
 last_error_code text, last_error_message text, last_error_at timestamptz,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 started_at timestamptz, completed_at timestamptz, failed_at timestamptz,
 lease_token uuid, lease_until timestamptz, worker_id text,
 applied_revision integer
);
CREATE INDEX IF NOT EXISTS km_csit_v2_changes_ready ON km_csit_v2_changes(status,next_retry_at,lease_until);
CREATE INDEX IF NOT EXISTS km_csit_v2_changes_source ON km_csit_v2_changes(source_type,source_entity_id,version);

-- Test Report v1 jobs and their v2 analysis result (spec 5.4 + v1.4.1 C.2). The ids CSIT alone knows come from the Correlation Resolver.
CREATE TABLE IF NOT EXISTS km_csit_v2_analysis (
 v1_job_id uuid PRIMARY KEY,
 status text NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending','Queued','Skipped')),
 attempt_count integer NOT NULL DEFAULT 0,
 next_retry_at timestamptz,
 last_error_code text,
 analysis_result_id uuid UNIQUE,
 callback_id uuid,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

-- Deletion: v2 requests use the same table and worker; they add sources and an api_version.
ALTER TABLE km_csit_deletion_jobs ADD COLUMN IF NOT EXISTS api_version text NOT NULL DEFAULT 'v1';
ALTER TABLE km_csit_deletion_jobs DROP CONSTRAINT IF EXISTS km_csit_deletion_jobs_source_type_check;
ALTER TABLE km_csit_deletion_jobs ADD CONSTRAINT km_csit_deletion_jobs_source_type_check
 CHECK(source_type IN ('DocumentLibraryFile','TestReport','VerificationApplicationAttachment','VendorFile','EquipmentAttachment'));

-- One ordered outbox for every callback kind. ingestion2/deletion2/change/analysis are the v2 endpoints.
ALTER TABLE km_csit_v13_callbacks DROP CONSTRAINT IF EXISTS km_csit_v13_callbacks_kind_check;
ALTER TABLE km_csit_v13_callbacks ADD CONSTRAINT km_csit_v13_callbacks_kind_check
 CHECK(kind IN ('ingestion','deletion','ingestion2','deletion2','change','analysis'));
COMMIT;
