"""Durable equipment-aggregate-analysis requests (CSIT requirement doc, 2026-11-17). Shares the v1.3/v1.4 callback outbox: the Completed/
Failed callback goes through the same km_csit_v13_callbacks table and worker every other v1.3/v1.4 callback already uses."""
import uuid
from psycopg.types.json import Jsonb
from .errors import IntegrationError, LeaseLost
from .equipment_aggregate_models import build_equipment_aggregate_callback

class EquipmentAggregateRepository:
    """Mixed into V2Repository (via runtime wiring): depends on self.connect()/self._enqueue() from DocLibRepository."""
    def check_equipment_aggregate_schema(self):
        with self.connect() as c:
            c.execute("SELECT 1 FROM km_csit_equipment_aggregate_requests LIMIT 0")

    def submit_equipment_aggregate_request(self, request):
        """Persist-then-ack. The same requestId returns the original kmJobId; a different body is a conflict (spec part 3: Idempotency-Key
        corresponds to requestId)."""
        p = request.model_dump(mode="json")
        with self.connect() as c:
            row = c.execute("SELECT * FROM km_csit_equipment_aggregate_requests WHERE request_id=%s", (request.requestId,)).fetchone()
            if row:
                if row["request_payload"] != p:
                    raise IntegrationError("REQUEST_CONFLICT", "requestId already used for a different request")
                return row
            km_job = "KM-EQAGG-%06d" % c.execute("SELECT nextval('km_csit_equipment_aggregate_job_seq') AS n").fetchone()["n"]
            return c.execute("""INSERT INTO km_csit_equipment_aggregate_requests(request_id,km_job_id,module_code,apparatus_id,
                  manifest_hash,analysis_version,request_payload,requested_at,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'Accepted') RETURNING *""",
                (request.requestId, km_job, request.moduleCode, request.apparatusId, request.manifestHash, request.analysisVersion,
                 Jsonb(p), request.requestedAt)).fetchone()
    def get_equipment_aggregate_request(self, request_id):
        with self.connect() as c:
            return c.execute("SELECT * FROM km_csit_equipment_aggregate_requests WHERE request_id=%s", (request_id,)).fetchone()

    # ---- worker ----
    def claim_equipment_aggregate(self, worker_id, lease_seconds):
        with self.connect() as c:
            return c.execute("""WITH candidate AS (
               SELECT request_id FROM km_csit_equipment_aggregate_requests
               WHERE (status='Accepted' AND (next_retry_at IS NULL OR next_retry_at<=clock_timestamp()))
                  OR (status='Processing' AND lease_until<=clock_timestamp())
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
              UPDATE km_csit_equipment_aggregate_requests r SET status='Processing',phase='Synthesising',attempt_count=attempt_count+1,
               lease_token=%s,lease_until=clock_timestamp()+%s*interval '1 second',worker_id=%s,
               updated_at=clock_timestamp(),started_at=COALESCE(started_at,clock_timestamp()),next_retry_at=NULL
              FROM candidate WHERE r.request_id=candidate.request_id RETURNING r.*""", (uuid.uuid4(), lease_seconds, worker_id)).fetchone()
    def renew_equipment_aggregate(self, row, seconds):
        with self.connect() as c:
            if not c.execute("""UPDATE km_csit_equipment_aggregate_requests SET lease_until=clock_timestamp()+%s*interval '1 second'
              WHERE request_id=%s AND lease_token=%s AND lease_until>clock_timestamp() AND status='Processing' RETURNING request_id""",
              (seconds, row["request_id"], row["lease_token"])).fetchone():
                raise LeaseLost()
    def v2_jobs_for_files(self, file_ids):
        """The Completed v2 job rows the synthesis reads; nothing is downloaded, parsed or re-analysed here."""
        if not file_ids:
            return []
        with self.connect() as c:
            return c.execute("SELECT * FROM km_csit_v2_jobs WHERE document_id = ANY(%s::uuid[]) AND status='Completed'",
                              ([str(x) for x in file_ids],)).fetchall()
    def finish_equipment_aggregate(self, row, result, analyzed_at):
        with self.connect() as c:
            r = c.execute("""SELECT * FROM km_csit_equipment_aggregate_requests WHERE request_id=%s AND lease_token=%s
                AND lease_until>clock_timestamp() AND status='Processing' FOR UPDATE""", (row["request_id"], row["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()
            r = c.execute("""UPDATE km_csit_equipment_aggregate_requests SET status='Completed',phase='Completed',
              updated_at=clock_timestamp(),completed_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,next_retry_at=NULL,
              last_error_code=NULL,last_error_message=NULL,result_json=%s WHERE request_id=%s RETURNING *""",
              (Jsonb(result), row["request_id"])).fetchone()
            self._enqueue(c, "equipment_aggregate", str(r["request_id"]), build_equipment_aggregate_callback, r, "Completed",
                           result=result, analyzed_at=analyzed_at)
            return r
    def fail_equipment_aggregate(self, row, error, retry_delays):
        with self.connect() as c:
            r = c.execute("""SELECT * FROM km_csit_equipment_aggregate_requests WHERE request_id=%s AND lease_token=%s
                AND status='Processing' FOR UPDATE""", (row["request_id"], row["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()
            attempt = r["attempt_count"]
            delay = retry_delays[attempt - 1] if error.retryable and attempt <= len(retry_delays) else None
            if delay is not None:
                c.execute("""UPDATE km_csit_equipment_aggregate_requests SET status='Accepted',phase='RetryWait',
                  last_error_code=%s,last_error_message=%s,last_error_at=clock_timestamp(),updated_at=clock_timestamp(),
                  lease_token=NULL,lease_until=NULL,next_retry_at=clock_timestamp()+%s*interval '1 second' WHERE request_id=%s""",
                  (error.code, error.message, delay, row["request_id"]))
                return
            r = c.execute("""UPDATE km_csit_equipment_aggregate_requests SET status='Failed',phase='Failed',
              last_error_code=%s,last_error_message=%s,last_error_at=clock_timestamp(),failed_at=clock_timestamp(),
              updated_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,next_retry_at=NULL
              WHERE request_id=%s RETURNING *""", (error.code, error.message, row["request_id"])).fetchone()
            self._enqueue(c, "equipment_aggregate", str(r["request_id"]), build_equipment_aggregate_callback, r, "Failed", error=error)
