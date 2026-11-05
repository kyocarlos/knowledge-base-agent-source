"""Durable v2 jobs, metadata changes, v2 deletions and the analysis-result queue (spec v1.4). Shares the v1.3 callback outbox."""
import uuid
from psycopg.types.json import Jsonb
from .errors import IntegrationError, LeaseLost
from .doclib_repository import DocLibRepository, doc_file_id
from .v2_models import identity_key, build_job_callback, build_change_callback, build_analysis_payload

LIVE = ("Accepted", "Processing", "Completed")

class V2Repository(DocLibRepository):
    def check_schema(self):
        super().check_schema()
        with self.connect() as c:
            for table in ("km_csit_v2_jobs", "km_csit_v2_checkpoints", "km_csit_v2_changes", "km_csit_v2_analysis"):
                c.execute(f"SELECT 1 FROM {table} LIMIT 0")
            c.execute("SELECT api_version FROM km_csit_deletion_jobs LIMIT 0")

    # ---- document-jobs intake ----
    def submit_job(self, request):
        """Persist-then-ack. The same eventId returns the original kmJobId; a different body is a conflict."""
        p = request.model_dump(mode="json")
        d, src = p["document"], p["source"]
        key = identity_key(src["type"], src["entityId"], d["id"], d["version"])
        with self.connect() as c:
            if self.is_tombstoned(c, src["type"], key):
                raise IntegrationError("DOCUMENT_DELETED", "Document version was deleted; ingestion refused")
            row = c.execute("SELECT * FROM km_csit_v2_jobs WHERE event_id=%s", (request.eventId,)).fetchone()
            if row:
                if (str(row["source_entity_id"]), str(row["document_id"]), row["version"], row["expected_sha256"]) != \
                   (src["entityId"], d["id"], d["version"], d["sha256"]):
                    raise IntegrationError("JOB_CONFLICT", "eventId already used for a different document")
                return row
            if c.execute("""SELECT 1 FROM km_csit_v2_jobs WHERE source_type=%s AND source_entity_id=%s AND version=%s
                AND status IN ('Accepted','Processing','Completed')""", (src["type"], src["entityId"], d["version"])).fetchone():
                raise IntegrationError("CANONICAL_JOB_EXISTS", "An active ingestion already exists for this source version")
            km_job = "KM-ING-%06d" % c.execute("SELECT nextval('km_csit_v2_job_seq') AS n").fetchone()["n"]
            return c.execute("""INSERT INTO km_csit_v2_jobs(event_id,csit_job_id,km_job_id,event_type,source_type,source_entity_id,document_id,
                  version,request_payload,original_file_name,content_type,file_size_bytes,expected_sha256,occurred_at,status)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Accepted') RETURNING *""",
                (request.eventId, request.csitJobId, km_job, request.eventType, src["type"], src["entityId"], d["id"], d["version"],
                 Jsonb(p), d["originalFileName"], d["contentType"], d["sizeBytes"], d["sha256"], request.occurredAt)).fetchone()
    def get_job(self, event_id):
        with self.connect() as c:
            return c.execute("SELECT * FROM km_csit_v2_jobs WHERE event_id=%s", (event_id,)).fetchone()

    # ---- ingestion worker ----
    def claim_job(self, worker_id, lease_seconds):
        with self.connect() as c:
            r = c.execute("""WITH candidate AS (
               SELECT event_id FROM km_csit_v2_jobs
               WHERE (status='Accepted' AND (next_retry_at IS NULL OR next_retry_at<=clock_timestamp()))
                  OR (status='Processing' AND lease_until<=clock_timestamp())
               ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
              UPDATE km_csit_v2_jobs j SET status='Processing',phase='Downloading',attempt_count=attempt_count+1,
               lease_token=%s,lease_until=clock_timestamp()+%s*interval '1 second',worker_id=%s,
               updated_at=clock_timestamp(),started_at=COALESCE(started_at,clock_timestamp()),next_retry_at=NULL
              FROM candidate WHERE j.event_id=candidate.event_id RETURNING j.*""", (uuid.uuid4(), lease_seconds, worker_id)).fetchone()
            if r and r["attempt_count"] == 1:
                self._enqueue(c, "ingestion2", str(r["event_id"]), build_job_callback, r, "Processing")
            return r
    def _owned_job(self, c, job):
        r = c.execute("""SELECT * FROM km_csit_v2_jobs WHERE event_id=%s AND lease_token=%s
            AND lease_until>clock_timestamp() AND status='Processing' FOR UPDATE""", (job["event_id"], job["lease_token"])).fetchone()
        if not r or self.is_tombstoned(c, r["source_type"], identity_key(r["source_type"], r["source_entity_id"], r["document_id"], r["version"])):
            raise LeaseLost()
        return r
    def renew_job(self, job, seconds):
        with self.connect() as c:
            if not c.execute("""UPDATE km_csit_v2_jobs SET lease_until=clock_timestamp()+%s*interval '1 second'
              WHERE event_id=%s AND lease_token=%s AND lease_until>clock_timestamp() AND status='Processing' RETURNING event_id""",
              (seconds, job["event_id"], job["lease_token"])).fetchone():
                raise LeaseLost()
    def phase_job(self, job, phase):
        with self.connect() as c:
            self._owned_job(c, job)
            c.execute("UPDATE km_csit_v2_jobs SET phase=%s,updated_at=clock_timestamp() WHERE event_id=%s", (phase, job["event_id"]))
    def set_hash_job(self, job, digest):
        with self.connect() as c:
            self._owned_job(c, job)
            c.execute("UPDATE km_csit_v2_jobs SET content_sha256=%s WHERE event_id=%s", (digest, job["event_id"]))
    def checkpoint_job(self, job, phase, result):
        with self.connect() as c:
            self._owned_job(c, job)
            c.execute("""INSERT INTO km_csit_v2_checkpoints(event_id,phase,result) VALUES(%s,%s,%s)
              ON CONFLICT(event_id,phase) DO UPDATE SET result=excluded.result,completed_at=clock_timestamp()""",
              (job["event_id"], phase, Jsonb(result)))
    def overrides_job(self, job):
        """Metadata changes that arrived while the job ran are part of the index being written."""
        with self.connect() as c:
            r = c.execute("SELECT metadata_overrides FROM km_csit_v2_jobs WHERE event_id=%s", (job["event_id"],)).fetchone()
            return (r or {}).get("metadata_overrides") or {}
    def file_deleted_job(self, job):
        with self.connect() as c:
            return self.is_tombstoned(c, job["source_type"], identity_key(job["source_type"], job["source_entity_id"], job["document_id"], job["version"]))
    def finish_job(self, job, result, references):
        """Completed is terminal and is written together with its outbox row."""
        with self.connect() as c:
            self._owned_job(c, job)
            r = c.execute("""UPDATE km_csit_v2_jobs SET status='Completed',phase='Completed',updated_at=clock_timestamp(),
              completed_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,next_retry_at=NULL,last_error_code=NULL,
              last_error_message=NULL,result_json=%s,storage_references=%s,index_state='Active',supersede_pending=%s
              WHERE event_id=%s RETURNING *""",
              (Jsonb(result), Jsonb(references), bool(job["request_payload"].get("supersedes")), job["event_id"])).fetchone()
            self._enqueue(c, "ingestion2", str(r["event_id"]), build_job_callback, r, "Completed", result=result)
            return r
    def fail_job(self, job, error, retry_delays):
        with self.connect() as c:
            r = c.execute("SELECT * FROM km_csit_v2_jobs WHERE event_id=%s AND lease_token=%s AND status='Processing' FOR UPDATE",
                          (job["event_id"], job["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()
            attempt = r["attempt_count"]
            delay = retry_delays[attempt - 1] if error.retryable and attempt <= len(retry_delays) else None
            if delay is not None:
                c.execute("""UPDATE km_csit_v2_jobs SET status='Accepted',phase='RetryWait',last_error_code=%s,last_error_message=%s,
                  last_error_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,
                  next_retry_at=clock_timestamp()+%s*interval '1 second' WHERE event_id=%s""",
                  (error.code, error.message, delay, job["event_id"]))
                return
            r = c.execute("""UPDATE km_csit_v2_jobs SET status='Failed',phase='Failed',last_error_code=%s,last_error_message=%s,
              last_error_at=clock_timestamp(),failed_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=NULL,
              lease_until=NULL,next_retry_at=NULL WHERE event_id=%s RETURNING *""", (error.code, error.message, job["event_id"])).fetchone()
            self._enqueue(c, "ingestion2", str(r["event_id"]), build_job_callback, r, "Failed", error=error)

    # ---- replacing a version (spec 6.1): the old index is retired only after the new one is Completed ----
    def next_supersede(self):
        with self.connect() as c:
            return c.execute("""SELECT * FROM km_csit_v2_jobs WHERE supersede_pending AND status='Completed'
              ORDER BY updated_at LIMIT 1""").fetchone()
    def retire_old(self, job):
        old = job["request_payload"]["supersedes"]
        with self.connect() as c:
            c.execute("""UPDATE km_csit_v2_jobs SET index_state='Superseded',superseded_at=clock_timestamp()
              WHERE document_id=%s AND version=%s AND expected_sha256=%s AND status='Completed' AND event_id<>%s""",
              (old["oldDocumentId"], old["oldVersion"], old["oldSha256"], job["event_id"]))
    def supersede_done(self, job):
        with self.connect() as c:
            c.execute("UPDATE km_csit_v2_jobs SET supersede_pending=false WHERE event_id=%s", (job["event_id"],))

    # ---- metadata changes (spec 6.2) ----
    def submit_change(self, request):
        p = request.model_dump(mode="json")
        ident = (request.sourceType, request.sourceEntityId, request.version)
        with self.connect() as c:
            key = request.key()
            if self.is_tombstoned(c, request.sourceType, key):
                raise IntegrationError("DOCUMENT_DELETED", "Document version was deleted")
            row = c.execute("SELECT * FROM km_csit_v2_changes WHERE change_id=%s", (request.changeId,)).fetchone()
            if row:
                if row["request_payload"] != p:
                    raise IntegrationError("CHANGE_CONFLICT", "changeId already used for a different change")
                return row
            known = c.execute("""SELECT 1 FROM km_csit_v2_jobs WHERE source_type=%s AND source_entity_id=%s AND version=%s
                UNION ALL SELECT 1 FROM km_csit_doclib_jobs WHERE %s='DocumentLibraryFile' AND document_file_id=%s
                UNION ALL SELECT 1 FROM km_csit_ingestion_jobs WHERE %s='TestReport' AND document_id=%s AND version=%s LIMIT 1""",
                (*ident, request.sourceType, request.documentId, request.sourceType, str(request.documentId), request.version)).fetchone()
            if not known:
                raise IntegrationError("DOCUMENT_NOT_FOUND", "No ingested document for this source version")
            top = c.execute("""SELECT max(source_revision) AS m FROM km_csit_v2_changes WHERE source_type=%s AND source_entity_id=%s
                AND version=%s AND status<>'Cancelled'""", ident).fetchone()["m"]
            if top is not None and request.sourceRevision <= top:
                raise IntegrationError("STALE_REVISION", "sourceRevision is not newer than the last accepted revision")
            km_job = "KM-CHANGE-%06d" % c.execute("SELECT nextval('km_csit_v2_change_seq') AS n").fetchone()["n"]
            return c.execute("""INSERT INTO km_csit_v2_changes(change_id,km_change_job_id,source_type,source_entity_id,document_id,version,
                  source_revision,request_payload,occurred_at,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'Accepted') RETURNING *""",
                (request.changeId, km_job, request.sourceType, request.sourceEntityId, request.documentId, request.version,
                 request.sourceRevision, Jsonb(p), request.occurredAt)).fetchone()
    def claim_change(self, worker_id, lease_seconds):
        """In revision order per document, and only once the document's own ingestion is no longer running."""
        with self.connect() as c:
            r = c.execute("""WITH candidate AS (
               SELECT c.change_id FROM km_csit_v2_changes c
               WHERE ((c.status='Accepted' AND (c.next_retry_at IS NULL OR c.next_retry_at<=clock_timestamp()))
                   OR (c.status='Processing' AND c.lease_until<=clock_timestamp()))
                 AND NOT EXISTS(SELECT 1 FROM km_csit_v2_changes p WHERE p.source_type=c.source_type AND p.source_entity_id=c.source_entity_id
                      AND p.version=c.version AND p.source_revision<c.source_revision AND p.status IN ('Accepted','Processing'))
                 AND NOT EXISTS(SELECT 1 FROM km_csit_v2_jobs j WHERE j.source_type=c.source_type AND j.source_entity_id=c.source_entity_id
                      AND j.version=c.version AND j.status IN ('Accepted','Processing'))
                 AND NOT EXISTS(SELECT 1 FROM km_csit_doclib_jobs d WHERE c.source_type='DocumentLibraryFile'
                      AND d.document_file_id=c.document_id AND d.status IN ('Accepted','Processing'))
               ORDER BY c.created_at FOR UPDATE OF c SKIP LOCKED LIMIT 1)
              UPDATE km_csit_v2_changes c SET status='Processing',attempt_count=attempt_count+1,
               lease_token=%s,lease_until=clock_timestamp()+%s*interval '1 second',worker_id=%s,
               updated_at=clock_timestamp(),started_at=COALESCE(started_at,clock_timestamp()),next_retry_at=NULL
              FROM candidate WHERE c.change_id=candidate.change_id RETURNING c.*""", (uuid.uuid4(), lease_seconds, worker_id)).fetchone()
            if r and r["attempt_count"] == 1:
                self._enqueue(c, "change", str(r["change_id"]), build_change_callback, r, "Processing")
            return r
    def renew_change(self, change, seconds):
        with self.connect() as c:
            if not c.execute("""UPDATE km_csit_v2_changes SET lease_until=clock_timestamp()+%s*interval '1 second'
              WHERE change_id=%s AND lease_token=%s AND lease_until>clock_timestamp() AND status='Processing' RETURNING change_id""",
              (seconds, change["change_id"], change["lease_token"])).fetchone():
                raise LeaseLost()
    def change_target(self, change):
        """The completed index this change applies to: ('v2'|'doclib'|'report', row) or None."""
        with self.connect() as c:
            r = c.execute("""SELECT * FROM km_csit_v2_jobs WHERE source_type=%s AND source_entity_id=%s AND version=%s
                AND status='Completed' ORDER BY created_at DESC LIMIT 1""",
                (change["source_type"], change["source_entity_id"], change["version"])).fetchone()
            if r:
                return "v2", r
            if change["source_type"] == "DocumentLibraryFile":
                r = c.execute("SELECT * FROM km_csit_doclib_jobs WHERE document_file_id=%s AND status='Completed' ORDER BY created_at DESC LIMIT 1",
                              (change["document_id"],)).fetchone()
                return ("doclib", r) if r else None
            if change["source_type"] == "TestReport":
                r = c.execute("SELECT * FROM km_csit_ingestion_jobs WHERE document_id=%s AND version=%s AND status='Completed' LIMIT 1",
                              (str(change["document_id"]), change["version"])).fetchone()
                return ("report", r) if r else None
            return None
    def finish_change(self, change, overrides_for=None):
        with self.connect() as c:
            r = c.execute("""SELECT * FROM km_csit_v2_changes WHERE change_id=%s AND lease_token=%s AND lease_until>clock_timestamp()
                AND status='Processing' FOR UPDATE""", (change["change_id"], change["lease_token"])).fetchone()
            if not r or self.is_tombstoned(c, r["source_type"], identity_key(r["source_type"], r["source_entity_id"], r["document_id"], r["version"])):
                raise LeaseLost()
            if overrides_for is not None:
                c.execute("""UPDATE km_csit_v2_jobs SET metadata_overrides=%s,source_revision=%s WHERE event_id=%s AND source_revision<=%s""",
                          (Jsonb(overrides_for["overrides"]), r["source_revision"], overrides_for["event_id"], r["source_revision"]))
            r = c.execute("""UPDATE km_csit_v2_changes SET status='Completed',updated_at=clock_timestamp(),completed_at=clock_timestamp(),
              lease_token=NULL,lease_until=NULL,next_retry_at=NULL,last_error_code=NULL,last_error_message=NULL,applied_revision=source_revision
              WHERE change_id=%s RETURNING *""", (change["change_id"],)).fetchone()
            self._enqueue(c, "change", str(r["change_id"]), build_change_callback, r, "Completed")
    def fail_change(self, change, error, retry_delays):
        with self.connect() as c:
            r = c.execute("SELECT * FROM km_csit_v2_changes WHERE change_id=%s AND lease_token=%s AND status='Processing' FOR UPDATE",
                          (change["change_id"], change["lease_token"])).fetchone()
            if not r:
                raise LeaseLost()
            attempt = r["attempt_count"]
            delay = retry_delays[attempt - 1] if error.retryable and attempt <= len(retry_delays) else None
            if delay is not None:
                c.execute("""UPDATE km_csit_v2_changes SET status='Accepted',last_error_code=%s,last_error_message=%s,
                  last_error_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,
                  next_retry_at=clock_timestamp()+%s*interval '1 second' WHERE change_id=%s""",
                  (error.code, error.message, delay, change["change_id"]))
                return
            r = c.execute("""UPDATE km_csit_v2_changes SET status='Failed',last_error_code=%s,last_error_message=%s,
              last_error_at=clock_timestamp(),failed_at=clock_timestamp(),updated_at=clock_timestamp(),lease_token=NULL,
              lease_until=NULL,next_retry_at=NULL WHERE change_id=%s RETURNING *""", (error.code, error.message, change["change_id"])).fetchone()
            self._enqueue(c, "change", str(r["change_id"]), build_change_callback, r, "Failed", error=error)
    def get_change(self, change_id):
        with self.connect() as c:
            return c.execute("SELECT * FROM km_csit_v2_changes WHERE change_id=%s", (change_id,)).fetchone()

    # ---- v2 deletion intake (spec 7.2) ----
    def submit_deletion_v2(self, request):
        """Persist, tombstone and cancel running work in one transaction; only then is 202 returned."""
        p = request.model_dump(mode="json")
        res = request.resource
        stype, skey = res.sourceType, res.key()
        with self.connect() as c:
            row = c.execute("SELECT * FROM km_csit_deletion_jobs WHERE deletion_request_id=%s", (request.deletionRequestId,)).fetchone()
            if row:
                if row["source_type"] != stype or row["source_key"] != skey:
                    raise IntegrationError("DELETION_CONFLICT", "deletionRequestId already used for a different resource")
                return row
            if stype != "DocumentLibraryFile":
                known = c.execute("""SELECT event_id,expected_sha256 FROM km_csit_v2_jobs WHERE source_entity_id=%s AND document_id=%s AND version=%s""",
                                  (res.sourceEntityId, res.documentId, res.version)).fetchall()
                if known and (all(k["expected_sha256"] != res.sha256 for k in known) or all(k["event_id"] != res.canonicalIngestionEventId for k in known)):
                    raise IntegrationError("RESOURCE_MISMATCH", "sha256 or canonicalIngestionEventId does not match the analysed version")
            km_job = "KM-DEL-%06d" % c.execute("SELECT nextval('km_csit_deletion_job_seq') AS n").fetchone()["n"]
            row = c.execute("""INSERT INTO km_csit_deletion_jobs(deletion_request_id,km_deletion_job_id,request_payload,reason_code,
                source_type,source_key,resource,requested_at,status,api_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'Accepted','v2') RETURNING *""",
                (request.deletionRequestId, km_job, Jsonb(p), request.reasonCode, stype, skey, Jsonb(res.exec_resource()), request.requestedAt)).fetchone()
            c.execute("""INSERT INTO km_csit_tombstones(source_type,source_key,deletion_request_id) VALUES(%s,%s,%s)
                ON CONFLICT(source_type,source_key) DO NOTHING""", (stype, skey, request.deletionRequestId))
            ident = (res.sourceEntityId, res.documentId, res.version)
            c.execute("""UPDATE km_csit_v2_jobs SET status='Cancelled',phase='Cancelled',lease_token=NULL,lease_until=NULL,next_retry_at=NULL,
              updated_at=clock_timestamp() WHERE source_entity_id=%s AND document_id=%s AND version=%s AND status IN ('Accepted','Processing')""", ident)
            c.execute("""UPDATE km_csit_v2_changes SET status='Cancelled',lease_token=NULL,lease_until=NULL,next_retry_at=NULL,
              updated_at=clock_timestamp() WHERE source_entity_id=%s AND document_id=%s AND version=%s AND status IN ('Accepted','Processing')""", ident)
            if stype == "DocumentLibraryFile":
                c.execute("""UPDATE km_csit_doclib_jobs SET status='Cancelled',phase='Cancelled',lease_token=NULL,lease_until=NULL,
                  next_retry_at=NULL,updated_at=clock_timestamp() WHERE document_file_id=%s AND status IN ('Accepted','Processing')""", (res.documentId,))
            return row

    # ---- cleanup support for v2 sources (used by DeletionExecutor) ----
    def _v2_where(self, job):
        r = job["resource"]
        return "source_entity_id=%s AND document_id=%s AND version=%s", (r["sourceEntityId"], r["documentId"], r["version"])
    def v2_jobs_for_resource(self, job):
        if job["source_type"] == "DocumentLibraryFile":
            return []
        where, args = self._v2_where(job)
        with self.connect() as c:
            return c.execute(f"SELECT event_id,km_job_id,storage_references FROM km_csit_v2_jobs WHERE {where}", args).fetchall()
    def purge_doclib_metadata(self, job):
        n = super().purge_doclib_metadata(job)
        if job["source_type"] == "DocumentLibraryFile":
            return n
        where, args = self._v2_where(job)
        with self.connect() as c:
            n += c.execute(f"""UPDATE km_csit_v2_jobs SET result_json=NULL,storage_references='{{}}',content_sha256=NULL,request_payload='{{}}',
              original_file_name='[deleted]',metadata_overrides='{{}}',supersede_pending=false,
              status=CASE WHEN status='Completed' THEN 'Deleted' ELSE status END
              WHERE {where} AND (result_json IS NOT NULL OR storage_references<>'{{}}' OR request_payload<>'{{}}' OR metadata_overrides<>'{{}}')""", args).rowcount
            c.execute(f"DELETE FROM km_csit_v2_checkpoints WHERE event_id IN (SELECT event_id FROM km_csit_v2_jobs WHERE {where})", args)
            c.execute(f"UPDATE km_csit_v2_changes SET request_payload='{{}}' WHERE {where} AND request_payload<>'{{}}'", args)
        return n
    def metadata_residue(self, job):
        n = super().metadata_residue(job)
        if job["source_type"] == "DocumentLibraryFile":
            return n
        where, args = self._v2_where(job)
        with self.connect() as c:
            n += c.execute(f"""SELECT count(*) AS n FROM km_csit_v2_jobs WHERE {where} AND
              (result_json IS NOT NULL OR storage_references<>'{{}}' OR request_payload<>'{{}}' OR metadata_overrides<>'{{}}')""", args).fetchone()["n"]
        return n

    # ---- Test Report v1 -> v2 analysis-results (spec 5.4) ----
    def next_unreported_report(self):
        """A v1 Test Report job whose Completed status the CSIT side already acknowledged and that has no v2 result queued yet."""
        with self.connect() as c:
            return c.execute("""SELECT j.* FROM km_csit_ingestion_jobs j
              WHERE j.status='Completed' AND NOT EXISTS(SELECT 1 FROM km_csit_v2_analysis a WHERE a.v1_job_id=j.job_id)
                AND EXISTS(SELECT 1 FROM km_csit_callback_deliveries d WHERE d.job_id=j.job_id AND d.status='Delivered' AND d.payload->>'status'='Completed')
              ORDER BY j.updated_at LIMIT 1""").fetchone()
    def queue_analysis(self, v1_job, fields, result, analyzed_at):
        analysis_id, callback_id = uuid.uuid4(), uuid.uuid4()
        payload = build_analysis_payload(callback_id, analysis_id, result=result, analyzed_at=analyzed_at, **fields)
        with self.connect() as c:
            if not c.execute("""INSERT INTO km_csit_v2_analysis(v1_job_id,analysis_result_id,callback_id) VALUES(%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING v1_job_id""", (v1_job["job_id"], analysis_id, callback_id)).fetchone():
                return False
            c.execute("INSERT INTO km_csit_v13_callbacks(callback_id,kind,ref_id,payload) VALUES(%s,'analysis',%s,%s)",
                      (callback_id, str(v1_job["job_id"]), Jsonb(payload)))
            return True
    def skip_analysis(self, v1_job):
        """Nothing sendable for this job (no readable extraction); record it so the poller does not retry forever."""
        with self.connect() as c:
            c.execute("INSERT INTO km_csit_v2_analysis(v1_job_id,analysis_result_id,callback_id) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                      (v1_job["job_id"], uuid.uuid4(), uuid.uuid4()))
