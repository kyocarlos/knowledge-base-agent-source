-- Equipment-level cross-document synthesis (CSIT requirement doc, 2026-11-17). One row per CSIT request (dedup on request_id); the
-- callback is delivered through the existing km_csit_v13_callbacks outbox (kind='equipment_aggregate'), the same mechanism every other
-- v1.3/v1.4 callback already uses, so nothing new is added for delivery, retry or ordering.
CREATE SEQUENCE IF NOT EXISTS km_csit_equipment_aggregate_job_seq;

CREATE TABLE IF NOT EXISTS km_csit_equipment_aggregate_requests (
  request_id uuid PRIMARY KEY,
  km_job_id text NOT NULL UNIQUE,
  module_code text NOT NULL,
  apparatus_id text NOT NULL,
  manifest_hash text NOT NULL CHECK(manifest_hash ~ '^[0-9a-f]{64}$'),
  analysis_version text NOT NULL,
  request_payload jsonb NOT NULL,
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
  result_json jsonb
);
CREATE INDEX IF NOT EXISTS km_csit_equipment_aggregate_requests_ready
  ON km_csit_equipment_aggregate_requests(status,next_retry_at,lease_until);
CREATE INDEX IF NOT EXISTS km_csit_equipment_aggregate_requests_apparatus
  ON km_csit_equipment_aggregate_requests(apparatus_id,module_code);

-- The callback outbox's kind check must know the new kind, or every enqueue of one fails closed (CheckViolation), not silently.
ALTER TABLE km_csit_v13_callbacks DROP CONSTRAINT IF EXISTS km_csit_v13_callbacks_kind_check;
ALTER TABLE km_csit_v13_callbacks ADD CONSTRAINT km_csit_v13_callbacks_kind_check
 CHECK(kind IN ('ingestion','deletion','ingestion2','deletion2','change','analysis','equipment_aggregate'));
