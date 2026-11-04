"""Durable document-library jobs, deletion jobs, tombstones and the ordered callback outbox (spec v1.3)."""
import uuid
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .errors import IntegrationError, LeaseLost
from .doclib_models import build_ingestion_callback, build_deletion_callback

class DocLibRepository:
    def __init__(self, db_url):
        self.db_url = db_url
    def connect(self):
        return psycopg.connect(self.db_url, row_factory=dict_row)
    def check_schema(self):
        with self.connect() as c:
            for table in ("km_csit_doclib_jobs", "km_csit_doclib_checkpoints", "km_csit_deletion_jobs",
                          "km_csit_tombstones", "km_csit_v13_callbacks"):
                c.execute(f"SELECT 1 FROM {table} LIMIT 0")

    # ---- tombstones ----
    def is_tombstoned(self, c, source_type, source_key):
        return c.execute("SELECT 1 FROM km_csit_tombstones WHERE source_type=%s AND source_key=%s",
                         (source_type, source_key)).fetchone() is not None
    def file_deleted(self, document_file_id):
        with self.connect() as c:
            return self.is_tombstoned(c, "DocumentLibraryFile", str(document_file_id))
    def v1_job_ids(self, document_id, version):
        try:
            with self.connect() as c:
                return [str(r["job_id"]) for r in c.execute("SELECT job_id FROM km_csit_ingestion_jobs WHERE document_id=%s AND version=%s",
                                                           (str(document_id), version))]
        except psycopg.errors.UndefinedTable:
            return []
    def v1_report_is_tombstoned(self, document_id, version):
        """Used by the Test Report v1 worker; any entity of the deleted document/version blocks reprocessing."""
        try:
            with self.connect() as c:
                return c.execute("SELECT 1 FROM km_csit_tombstones WHERE source_type IN ('TestReport','VerificationApplicationAttachment') AND source_key LIKE %s LIMIT 1",
                                 (f"{document_id}:{version}:%",)).fetchone() is not None
        except psycopg.errors.UndefinedTable:
            return False

    # ---- document-library intake ----
    def submit(self, request):
        """Persist-then-ack. The same csitJobId returns the original kmJobId; a different body is a conflict."""
        p = request.model_dump(mode="json")
        raw_file = p["file"]
        with self.connect() as c:
            if self.is_tombstoned(c, "DocumentLibraryFile", str(request.documentFileId)):
                raise IntegrationError("DOCUMENT_DELETED", "Document was deleted; ingestion refused")
            km_job = "KM-DOC-%06d" % c.execute("SELECT nextval('km_csit_doclib_job_seq') AS n").fetchone()["n"]
            row = c.execute("""INSERT INTO km_csit_doclib_jobs(csit_job_id,km_job_id,document_file_id,request_payload,original_file_name,
                  standard_file_name,content_type,file_size_bytes,expected_sha256,occurred_at,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Accepted')
                ON CONFLICT(csit_job_id) DO NOTHING RETURNING *""",
                (request.csitJobId, km_job, request.documentFileId, Jsonb(p), raw_file["originalFileName"], raw_file["standardFileName"],
                 raw_file["contentType"], raw_file["fileSizeBytes"], raw_file["sha256"], request.occurredAt)).fetchone()
            if row:
                return row
            row = c.execute("SELECT * FROM km_csit_doclib_jobs WHERE csit_job_id=%s", (request.csitJobId,)).fetchone()
            if str(row["document_file_id"]) != str(request.documentFileId) or row["expected_sha256"] != raw_file["sha256"]:
                raise IntegrationError("JOB_CONFLICT", "csitJobId already used for a different file")
            return row
    def get_job(self, csit_job_id):
        with self.connect() as c:
            return c.execute("SELECT * FROM km_csit_doclib_jobs WHERE csit_job_id=%s", (csit_job_id,)).fetchone()

    # ---- outbox ----
    def _enqueue(self, c, kind, ref_id, builder, job, status, **kw):
        callback_id = uuid.uuid4()
        payload = builder(callback_id, job, status, **kw)
        c.execute("INSERT INTO km_csit_v13_callbacks(callback_id,kind,ref_id,payload) VALUES(%s,%s,%s,%s)",
                  (callback_id, kind, ref_id, Jsonb(payload)))
    def claim_callback(self, seconds):
        with self.connect() as c:
            return c.execute("""WITH candidate AS(
              SELECT d.callback_id FROM km_csit_v13_callbacks d WHERE
               (d.status='Pending' AND (d.next_retry_at IS NULL OR d.next_retry_at<=clock_timestamp())
                OR d.status='Delivering' AND d.lease_until<=clock_timestamp())
               AND NOT EXISTS(SELECT 1 FROM km_csit_v13_callbacks prior WHERE prior.kind=d.kind AND prior.ref_id=d.ref_id
                AND prior.sequence<d.sequence AND prior.status IN ('Pending','Delivering'))
              ORDER BY d.sequence FOR UPDATE OF d SKIP LOCKED LIMIT 1)
             UPDATE km_csit_v13_callbacks d SET status='Delivering',attempt_count=attempt_count+1,
              lease_token=%s,lease_until=clock_timestamp()+%s*interval '1 second'
             FROM candidate WHERE d.callback_id=candidate.callback_id RETURNING d.*""", (uuid.uuid4(), seconds)).fetchone()
    def callback_result(self, delivery, error, delays):
        attempt = delivery["attempt_count"]
        delay = delays[attempt - 1] if error and error.retryable and attempt <= len(delays) else None
        status = "Delivered" if error is None else ("Pending" if delay is not None else "Failed")
        with self.connect() as c:
            r = c.execute("""UPDATE km_csit_v13_callbacks SET status=%s,lease_token=NULL,lease_until=NULL,
              next_retry_at=CASE WHEN %s::integer IS NULL THEN NULL ELSE clock_timestamp()+%s*interval '1 second' END,
              last_error_code=%s,last_error_at=CASE WHEN %s THEN clock_timestamp() ELSE NULL END,
              delivered_at=CASE WHEN %s='Delivered' THEN clock_timestamp() ELSE NULL END
              WHERE callback_id=%s AND lease_token=%s AND lease_until>clock_timestamp() RETURNING callback_id""",
              (status, delay, delay, error.code if error else None, error is not None, status,
               delivery["callback_id"], delivery["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()

    # ---- ingestion worker ----
    def claim(self, worker_id, lease_seconds):
        with self.connect() as c:
            r = c.execute("""WITH candidate AS (
               SELECT csit_job_id FROM km_csit_doclib_jobs
               WHERE (status='Accepted' AND (next_retry_at IS NULL OR next_retry_at<=clock_timestamp()))
                  OR (status='Processing' AND lease_until<=clock_timestamp())
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
              UPDATE km_csit_doclib_jobs j SET status='Processing',phase='Downloading',attempt_count=attempt_count+1,
               lease_token=%s,lease_until=clock_timestamp()+%s*interval '1 second',worker_id=%s,
               updated_at=clock_timestamp(),started_at=COALESCE(started_at,clock_timestamp()),next_retry_at=NULL
              FROM candidate WHERE j.csit_job_id=candidate.csit_job_id RETURNING j.*""",
              (uuid.uuid4(), lease_seconds, worker_id)).fetchone()
            # Processing is announced once. A retry after a transient failure never re-announces it (no status regress).
            if r and r["attempt_count"] == 1:
                self._enqueue(c, "ingestion", str(r["csit_job_id"]), build_ingestion_callback, r, "Processing")
            return r
    def _owned(self, c, job):
        r = c.execute("""SELECT * FROM km_csit_doclib_jobs WHERE csit_job_id=%s AND lease_token=%s
            AND lease_until>clock_timestamp() AND status='Processing' FOR UPDATE""", (job["csit_job_id"], job["lease_token"])).fetchone()
        if not r:
            raise LeaseLost()
        if self.is_tombstoned(c, "DocumentLibraryFile", str(r["document_file_id"])):
            raise LeaseLost()
        return r
    def renew(self, job, seconds):
        with self.connect() as c:
            r = c.execute("""UPDATE km_csit_doclib_jobs SET lease_until=clock_timestamp()+%s*interval '1 second'
              WHERE csit_job_id=%s AND lease_token=%s AND lease_until>clock_timestamp() AND status='Processing'
              RETURNING csit_job_id""", (seconds, job["csit_job_id"], job["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()
    def phase(self, job, phase):
        with self.connect() as c:
            self._owned(c, job)
            c.execute("UPDATE km_csit_doclib_jobs SET phase=%s,updated_at=clock_timestamp() WHERE csit_job_id=%s", (phase, job["csit_job_id"]))
    def set_hash(self, job, digest):
        with self.connect() as c:
            self._owned(c, job)
            c.execute("UPDATE km_csit_doclib_jobs SET content_sha256=%s WHERE csit_job_id=%s", (digest, job["csit_job_id"]))
    def checkpoints(self, job):
        with self.connect() as c:
            return {r["phase"]: r["result"] for r in c.execute("SELECT phase,result FROM km_csit_doclib_checkpoints WHERE csit_job_id=%s", (job["csit_job_id"],))}
    def checkpoint(self, job, phase, result):
        with self.connect() as c:
            self._owned(c, job)
            c.execute("""INSERT INTO km_csit_doclib_checkpoints(csit_job_id,phase,result) VALUES(%s,%s,%s)
              ON CONFLICT(csit_job_id,phase) DO UPDATE SET result=excluded.result,completed_at=clock_timestamp()""",
              (job["csit_job_id"], phase, Jsonb(result)))
    def finish(self, job, result, references):
        """Completed is terminal and is written together with its outbox row."""
        with self.connect() as c:
            self._owned(c, job)
            r = c.execute("""UPDATE km_csit_doclib_jobs SET status='Completed',phase='Completed',updated_at=clock_timestamp(),
              completed_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,next_retry_at=NULL,last_error_code=NULL,
              last_error_message=NULL,result_json=%s,storage_references=%s WHERE csit_job_id=%s RETURNING *""",
              (Jsonb(result), Jsonb(references), job["csit_job_id"])).fetchone()
            self._enqueue(c, "ingestion", str(r["csit_job_id"]), build_ingestion_callback, r, "Completed", result=result)
    def fail(self, job, error, retry_delays):
        with self.connect() as c:
            r = c.execute("SELECT * FROM km_csit_doclib_jobs WHERE csit_job_id=%s AND lease_token=%s AND status='Processing' FOR UPDATE",
                          (job["csit_job_id"], job["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()
            attempt = r["attempt_count"]
            delay = retry_delays[attempt - 1] if error.retryable and attempt <= len(retry_delays) else None
            if delay is not None:
                c.execute("""UPDATE km_csit_doclib_jobs SET status='Accepted',phase='RetryWait',last_error_code=%s,last_error_message=%s,
                  last_error_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,
                  next_retry_at=clock_timestamp()+%s*interval '1 second' WHERE csit_job_id=%s""",
                  (error.code, error.message, delay, job["csit_job_id"]))
                return
            r = c.execute("""UPDATE km_csit_doclib_jobs SET status='Failed',phase='Failed',last_error_code=%s,last_error_message=%s,
              last_error_at=clock_timestamp(),failed_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=NULL,
              lease_until=NULL,next_retry_at=NULL WHERE csit_job_id=%s RETURNING *""",
              (error.code, error.message, job["csit_job_id"])).fetchone()
            self._enqueue(c, "ingestion", str(r["csit_job_id"]), build_ingestion_callback, r, "Failed", error=error)

    # ---- deletion intake ----
    def submit_deletion(self, request):
        """Persist, tombstone and cancel running work in one transaction; only then is 202 returned."""
        p = request.model_dump(mode="json")
        resource = request.resource.wire()
        stype, skey = request.resource.sourceType, request.resource.key()
        with self.connect() as c:
            km_job = "KM-DEL-%06d" % c.execute("SELECT nextval('km_csit_deletion_job_seq') AS n").fetchone()["n"]
            row = c.execute("""INSERT INTO km_csit_deletion_jobs(deletion_request_id,km_deletion_job_id,request_payload,reason_code,
                source_type,source_key,resource,requested_at,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'Accepted')
                ON CONFLICT(deletion_request_id) DO NOTHING RETURNING *""",
                (request.deletionRequestId, km_job, Jsonb(p), request.reasonCode, stype, skey, Jsonb(resource), request.requestedAt)).fetchone()
            if not row:
                row = c.execute("SELECT * FROM km_csit_deletion_jobs WHERE deletion_request_id=%s", (request.deletionRequestId,)).fetchone()
                if row["source_type"] != stype or row["source_key"] != skey:
                    raise IntegrationError("DELETION_CONFLICT", "deletionRequestId already used for a different resource")
                return row
            c.execute("""INSERT INTO km_csit_tombstones(source_type,source_key,deletion_request_id) VALUES(%s,%s,%s)
                ON CONFLICT(source_type,source_key) DO NOTHING""", (stype, skey, request.deletionRequestId))
            if stype == "DocumentLibraryFile":
                # Stop same-source analysis and index rebuilds; a running worker loses its lease.
                c.execute("""UPDATE km_csit_doclib_jobs SET status='Cancelled',phase='Cancelled',lease_token=NULL,lease_until=NULL,
                  next_retry_at=NULL,updated_at=clock_timestamp() WHERE document_file_id=%s AND status IN ('Accepted','Processing')""",
                  (request.resource.documentFileId,))
            return row
    def get_deletion(self, deletion_request_id):
        with self.connect() as c:
            return c.execute("SELECT * FROM km_csit_deletion_jobs WHERE deletion_request_id=%s", (deletion_request_id,)).fetchone()

    # ---- deletion worker ----
    def claim_deletion(self, worker_id, lease_seconds):
        with self.connect() as c:
            r = c.execute("""WITH candidate AS (
               SELECT deletion_request_id FROM km_csit_deletion_jobs
               WHERE (status='Accepted' AND (next_retry_at IS NULL OR next_retry_at<=clock_timestamp()))
                  OR (status='Processing' AND lease_until<=clock_timestamp())
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
              UPDATE km_csit_deletion_jobs j SET status='Processing',phase='Cleaning',attempt_count=attempt_count+1,
               lease_token=%s,lease_until=clock_timestamp()+%s*interval '1 second',worker_id=%s,
               updated_at=clock_timestamp(),started_at=COALESCE(started_at,clock_timestamp()),next_retry_at=NULL
              FROM candidate WHERE j.deletion_request_id=candidate.deletion_request_id RETURNING j.*""",
              (uuid.uuid4(), lease_seconds, worker_id)).fetchone()
            if r and r["attempt_count"] == 1:
                self._enqueue(c, "deletion", str(r["deletion_request_id"]), build_deletion_callback, r, "Processing")
            return r
    def renew_deletion(self, job, seconds):
        with self.connect() as c:
            r = c.execute("""UPDATE km_csit_deletion_jobs SET lease_until=clock_timestamp()+%s*interval '1 second'
              WHERE deletion_request_id=%s AND lease_token=%s AND lease_until>clock_timestamp() AND status='Processing'
              RETURNING deletion_request_id""", (seconds, job["deletion_request_id"], job["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()
    def doclib_jobs_for_resource(self, job):
        """Local job rows (and therefore storage directories) that belong to exactly this source."""
        if job["source_type"] != "DocumentLibraryFile":
            return []
        with self.connect() as c:
            return c.execute("SELECT csit_job_id,km_job_id,storage_references FROM km_csit_doclib_jobs WHERE document_file_id=%s",
                             (job["resource"]["documentFileId"],)).fetchall()
    def purge_doclib_metadata(self, job):
        """Drop the analysed content for this source; the row stays as an audit stub with no content."""
        if job["source_type"] != "DocumentLibraryFile":
            return 0
        with self.connect() as c:
            n = c.execute("""UPDATE km_csit_doclib_jobs SET result_json=NULL,storage_references='{}',content_sha256=NULL,
              request_payload='{}',original_file_name='[deleted]',standard_file_name=NULL,
              status=CASE WHEN status='Completed' THEN 'Deleted' ELSE status END
              WHERE document_file_id=%s AND (result_json IS NOT NULL OR storage_references<>'{}' OR request_payload<>'{}')""",
              (job["resource"]["documentFileId"],)).rowcount
            c.execute("""DELETE FROM km_csit_doclib_checkpoints WHERE csit_job_id IN
              (SELECT csit_job_id FROM km_csit_doclib_jobs WHERE document_file_id=%s)""", (job["resource"]["documentFileId"],))
            return n
    def metadata_residue(self, job):
        if job["source_type"] != "DocumentLibraryFile":
            return 0
        with self.connect() as c:
            return c.execute("""SELECT count(*) AS n FROM km_csit_doclib_jobs WHERE document_file_id=%s AND
              (result_json IS NOT NULL OR storage_references<>'{}' OR request_payload<>'{}')""",
              (job["resource"]["documentFileId"],)).fetchone()["n"]
    def _owned_deletion(self, c, job):
        r = c.execute("""SELECT * FROM km_csit_deletion_jobs WHERE deletion_request_id=%s AND lease_token=%s
            AND lease_until>clock_timestamp() AND status='Processing' FOR UPDATE""", (job["deletion_request_id"], job["lease_token"])).fetchone()
        if not r:
            raise LeaseLost()
        return r
    def finish_deletion(self, job, result):
        with self.connect() as c:
            self._owned_deletion(c, job)
            r = c.execute("""UPDATE km_csit_deletion_jobs SET status='Completed',phase='Completed',updated_at=clock_timestamp(),
              completed_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,next_retry_at=NULL,last_error_code=NULL,
              last_error_message=NULL,cleanup_result=%s WHERE deletion_request_id=%s RETURNING *""",
              (Jsonb(result), job["deletion_request_id"])).fetchone()
            self._enqueue(c, "deletion", str(r["deletion_request_id"]), build_deletion_callback, r, "Completed", result=result)
    def fail_deletion(self, job, error, retry_delays):
        with self.connect() as c:
            r = c.execute("SELECT * FROM km_csit_deletion_jobs WHERE deletion_request_id=%s AND lease_token=%s AND status='Processing' FOR UPDATE",
                          (job["deletion_request_id"], job["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()
            attempt = r["attempt_count"]
            delay = retry_delays[attempt - 1] if error.retryable and attempt <= len(retry_delays) else None
            if delay is not None:
                c.execute("""UPDATE km_csit_deletion_jobs SET status='Accepted',phase='RetryWait',last_error_code=%s,last_error_message=%s,
                  last_error_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,
                  next_retry_at=clock_timestamp()+%s*interval '1 second' WHERE deletion_request_id=%s""",
                  (error.code, error.message, delay, job["deletion_request_id"]))
                return
            r = c.execute("""UPDATE km_csit_deletion_jobs SET status='Failed',phase='Failed',last_error_code=%s,last_error_message=%s,
              last_error_at=clock_timestamp(),failed_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=NULL,
              lease_until=NULL,next_retry_at=NULL WHERE deletion_request_id=%s RETURNING *""",
              (error.code, error.message, job["deletion_request_id"])).fetchone()
            self._enqueue(c, "deletion", str(r["deletion_request_id"]), build_deletion_callback, r, "Failed", error=error)
