"""PostgreSQL durable jobs, fenced leases, phase checkpoints and callback outbox."""
from datetime import datetime,timezone
import uuid
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from .errors import IntegrationError, LeaseLost
from .callbacks import build_callback_payload

class Repository:
    def __init__(self, db_url):
        self.db_url=db_url
    def connect(self):
        return psycopg.connect(self.db_url,row_factory=dict_row)
    def check_schema(self):
        with self.connect() as c:
            c.execute("SELECT job_id FROM km_csit_ingestion_jobs LIMIT 0")
            c.execute("SELECT job_id FROM km_csit_phase_checkpoints LIMIT 0")
            c.execute("SELECT job_id FROM km_csit_callback_deliveries LIMIT 0")
    def submit(self, request):
        p=request.model_dump(mode="json")
        refs=[p[x][y] for x in ("project","case","task") for y in ("id","number","name")]
        with self.connect() as c:
            r=c.execute("""INSERT INTO km_csit_ingestion_jobs
             (job_id,event_id,source_system,event_type,document_id,version,
              project_id,project_code,project_name,case_id,case_code,case_name,task_id,task_code,task_name,
              file_name,content_type,size_bytes,committed_at,request_payload,status)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Accepted')
             ON CONFLICT(source_system,document_id,version) DO NOTHING RETURNING *""",
             [uuid.uuid4(),p["eventId"],p["sourceSystem"],p["eventType"],p["documentId"],p["version"]]+refs+
             [p["document"]["fileName"],p["document"]["contentType"],p["document"]["sizeBytes"],p["committedAt"],Jsonb(p)]).fetchone()
            if r: return r
            r=c.execute("SELECT * FROM km_csit_ingestion_jobs WHERE source_system=%s AND document_id=%s AND version=%s",
                (p["sourceSystem"],p["documentId"],p["version"])).fetchone()
            old=dict(r["request_payload"]);new=dict(p)
            old.pop("eventId");new.pop("eventId")
            if old!=new: raise IntegrationError("SOURCE_VERSION_CONFLICT","Existing source version has different metadata")
            return r
    def _resume_attempt_base(self,c,job_id):
        row=c.execute("""SELECT detail_json FROM km_audit_events
         WHERE event_type='csit_job_resumed' AND detail_json::jsonb->>'job_id'=%s
         ORDER BY detail_json::jsonb->>'resumed_at' DESC LIMIT 1""",(str(job_id),)).fetchone()
        return int(__import__('json').loads(row['detail_json'])['previous']['attempt_count']) if row else 0

    def resume(self,job_id,identity,actor_user_id,operator_login,reason):
        import json,re
        from .errors import IntegrationError
        if not isinstance(reason,str) or not 1<=len(reason.strip())<=1000 or any(ord(x)<32 for x in reason):
            raise IntegrationError('RESUME_REASON_INVALID','A bounded single-line reason is required')
        if re.search(r'(?i)(bearer\s|basic\s|authorization\s*:|client_secret|password\s*=|eyJ[A-Za-z0-9_-]+\.)',reason):
            raise IntegrationError('RESUME_REASON_INVALID','Reason must not contain credentials')
        if not isinstance(operator_login,str) or not re.fullmatch(r'[A-Za-z0-9_.@-]{1,128}',operator_login):
            raise IntegrationError('RESUME_OPERATOR_INVALID','Authenticated operator identity required')
        if set(identity)!={'event_id','source_system','document_id','version'}:
            raise IntegrationError('RESUME_IDENTITY_REQUIRED','Complete expected source identity required')
        with self.connect() as c:
            actor=c.execute('SELECT user_id,status,is_admin FROM km_users WHERE user_id=%s FOR SHARE',(actor_user_id,)).fetchone()
            if not actor or actor['status']!='active' or not actor['is_admin']:
                raise IntegrationError('RESUME_ADMIN_REQUIRED','Active KM Control admin role required')
            r=c.execute('SELECT * FROM km_csit_ingestion_jobs WHERE job_id=%s FOR UPDATE',(job_id,)).fetchone()
            if not r:raise IntegrationError('RESUME_JOB_NOT_FOUND','Existing job required')
            if any(r[k]!=identity[k] for k in identity):
                raise IntegrationError('RESUME_IDENTITY_MISMATCH','Expected source identity does not match existing job')
            if r['status']!='Failed' or r['next_retry_at'] is not None:
                raise IntegrationError('RESUME_TERMINAL_FAILED_REQUIRED','Only terminal Failed jobs may be resumed')
            if r['lease_token'] is not None or r['lease_until'] is not None:
                raise IntegrationError('RESUME_LEASE_ACTIVE','Job must have no lease')
            callbacks=c.execute("""SELECT delivery_id,sequence,payload->>'status' AS callback_status,status,
             attempt_count,next_retry_at,last_error_code,last_error_at,created_at,delivered_at,lease_token,lease_until
             FROM km_csit_callback_deliveries WHERE job_id=%s ORDER BY sequence FOR UPDATE""",(job_id,)).fetchall()
            if any(x['status'] in ('Pending','Delivering') or x['next_retry_at'] is not None or x['lease_token'] is not None or x['lease_until'] is not None for x in callbacks):
                raise IntegrationError('RESUME_CALLBACK_ACTIVE','Prior callback delivery must be terminal')
            previous={k:r[k] for k in ['status','phase','attempt_count','download_attempt_count','last_error_code','last_error_message','last_error_at','started_at','updated_at','worker_id','next_retry_at','lease_until']}
            now=c.execute('SELECT clock_timestamp() AS now').fetchone()['now']
            audit_id=str(uuid.uuid4())
            details={'job_id':str(r['job_id']),'identity':identity,'previous':previous,'previous_callbacks':callbacks,
             'resumed_at':now.isoformat(),'operator_login':operator_login,'reason':reason.strip(),'resulting_status':'Accepted'}
            c.execute('INSERT INTO km_audit_events(event_id,occurred_at,actor_user_id,target_user_id,event_type,detail_json) VALUES(%s,%s,%s,NULL,%s,%s)',
             (audit_id,int(now.timestamp()),actor_user_id,'csit_job_resumed',json.dumps(details,default=str,separators=(',',':'),sort_keys=True)))
            updated=c.execute("""UPDATE km_csit_ingestion_jobs SET status='Accepted',phase='Accepted',
             next_retry_at=NULL,updated_at=%s WHERE job_id=%s RETURNING *""",(now,job_id)).fetchone()
            return {'job':self.response(updated),'auditId':audit_id,'previousStatus':'Failed','resumedAt':now.isoformat()}

    def get(self, job_id):
        with self.connect() as c:
            return c.execute("SELECT * FROM km_csit_ingestion_jobs WHERE job_id=%s",(job_id,)).fetchone()
    @staticmethod
    def response(r):
        return {"jobId":str(r["job_id"]),"sourceSystem":r["source_system"],"documentId":r["document_id"],
            "version":r["version"],"status":r["status"]}
    def _outbox(self,c,r,status,error=None):
        payload=build_callback_payload(r,status,error)
        c.execute("INSERT INTO km_csit_callback_deliveries(delivery_id,job_id,payload) VALUES(%s,%s,%s)",
            (uuid.uuid4(),r["job_id"],Jsonb(payload)))
    def claim(self,worker_id,lease_seconds):
        with self.connect() as c:
            r=c.execute("""WITH candidate AS (
              SELECT job_id FROM km_csit_ingestion_jobs
              WHERE ((status='Accepted') OR (status='Failed' AND next_retry_at<=clock_timestamp())
                OR (status='Processing' AND lease_until<=clock_timestamp()))
                AND (lease_until IS NULL OR lease_until<=clock_timestamp())
              ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
             ) UPDATE km_csit_ingestion_jobs j SET status='Processing',phase='Downloading',
             attempt_count=attempt_count+1, lease_token=%s, lease_until=clock_timestamp()+%s*interval '1 second',
             worker_id=%s, updated_at=clock_timestamp(),started_at=COALESCE(started_at,clock_timestamp()),
             next_retry_at=NULL
             FROM candidate WHERE j.job_id=candidate.job_id RETURNING j.*""",
             (uuid.uuid4(),lease_seconds,worker_id)).fetchone()
            if r:
                self._outbox(c,r,"Processing")
                r["_resume_attempt_base"]=self._resume_attempt_base(c,r["job_id"])
            return r
    def _owned(self,c,job):
        r=c.execute("""SELECT * FROM km_csit_ingestion_jobs WHERE job_id=%s AND lease_token=%s
            AND lease_until>clock_timestamp() AND status='Processing' FOR UPDATE""",
            (job["job_id"],job["lease_token"])).fetchone()
        if not r:raise LeaseLost()
        return r
    def renew(self,job,seconds):
        with self.connect() as c:
            r=c.execute("""UPDATE km_csit_ingestion_jobs SET lease_until=clock_timestamp()+%s*interval '1 second'
                WHERE job_id=%s AND lease_token=%s AND lease_until>clock_timestamp() AND status='Processing'
                RETURNING job_id""",(seconds,job["job_id"],job["lease_token"])).fetchone()
            if not r:raise LeaseLost()
    def phase(self,job,phase):
        with self.connect() as c:
            self._owned(c,job)
            c.execute("""UPDATE km_csit_ingestion_jobs SET phase=%s, updated_at=clock_timestamp(),
              download_attempt_count=download_attempt_count+CASE WHEN %s='Downloading' THEN 1 ELSE 0 END
              WHERE job_id=%s""",(phase,phase,job["job_id"]))
    def set_hash(self,job,digest):
        with self.connect() as c:
            r=self._owned(c,job)
            if r["content_sha256"] and r["content_sha256"]!=digest:
                raise IntegrationError("SOURCE_VERSION_CHANGED","Immutable source version content changed")
            c.execute("UPDATE km_csit_ingestion_jobs SET content_sha256=%s WHERE job_id=%s",(digest,job["job_id"]))
    def checkpoints(self,job):
        with self.connect() as c:
            return {r["phase"]:r["result"] for r in c.execute("SELECT phase,result FROM km_csit_phase_checkpoints WHERE job_id=%s",(job["job_id"],))}
    def checkpoint(self,job,phase,result):
        with self.connect() as c:
            self._owned(c,job)
            c.execute("""INSERT INTO km_csit_phase_checkpoints(job_id,phase,result) VALUES(%s,%s,%s)
              ON CONFLICT(job_id,phase) DO UPDATE SET result=excluded.result,completed_at=clock_timestamp()""",
              (job["job_id"],phase,Jsonb(result)))
    def finish(self,job,references,parser_version,extraction_version):
        with self.connect() as c:
            self._owned(c,job)
            r=c.execute("""UPDATE km_csit_ingestion_jobs SET status='Completed',phase='Completed',
                updated_at=clock_timestamp(),completed_at=clock_timestamp(),lease_token=NULL,lease_until=NULL,
                next_retry_at=NULL,last_error_code=NULL,last_error_message=NULL,
                storage_references=%s,parser_version=%s,extraction_version=%s,
                processing_duration_ms=EXTRACT(epoch FROM (clock_timestamp()-started_at))*1000
                WHERE job_id=%s RETURNING *""",
                (Jsonb(references),parser_version,extraction_version,job["job_id"])).fetchone()
            self._outbox(c,r,"Completed")
    def fail(self,job,error,retry_delays):
        with self.connect() as c:
            r=self._owned(c,job)
            attempt=r["attempt_count"]-job.get("_resume_attempt_base",0)
            delay=retry_delays[attempt-1] if error.retryable and attempt<=len(retry_delays) else None
            r=c.execute("""UPDATE km_csit_ingestion_jobs SET status='Failed',phase='Failed',
             last_error_code=%s,last_error_message=%s,last_error_at=clock_timestamp(),updated_at=clock_timestamp(),
             lease_token=NULL,lease_until=NULL,
             next_retry_at=CASE WHEN %s::integer IS NULL THEN NULL ELSE clock_timestamp()+%s*interval '1 second' END
             WHERE job_id=%s RETURNING *""",(error.code,error.message,delay,delay,job["job_id"])).fetchone()
            self._outbox(c,r,"Failed",error)
    def claim_callback(self,seconds):
        with self.connect() as c:
            return c.execute("""WITH candidate AS(
             SELECT d.delivery_id FROM km_csit_callback_deliveries d WHERE
              (d.status='Pending' AND (d.next_retry_at IS NULL OR d.next_retry_at<=clock_timestamp())
               OR d.status='Delivering' AND d.lease_until<=clock_timestamp())
              AND NOT EXISTS(SELECT 1 FROM km_csit_callback_deliveries prior
               WHERE prior.job_id=d.job_id AND prior.sequence<d.sequence AND prior.status IN ('Pending','Delivering'))
             ORDER BY d.sequence FOR UPDATE OF d SKIP LOCKED LIMIT 1)
             UPDATE km_csit_callback_deliveries d SET status='Delivering',attempt_count=attempt_count+1,
              lease_token=%s,lease_until=clock_timestamp()+%s*interval '1 second'
             FROM candidate WHERE d.delivery_id=candidate.delivery_id RETURNING d.*""",(uuid.uuid4(),seconds)).fetchone()
    def callback_result(self,delivery,error,delays):
        attempt=delivery["attempt_count"]
        delay=delays[attempt-1] if error and error.retryable and attempt<=len(delays) else None
        status="Delivered" if error is None else ("Pending" if delay is not None else "Failed")
        with self.connect() as c:
            r=c.execute("""UPDATE km_csit_callback_deliveries SET status=%s,lease_token=NULL,lease_until=NULL,
             next_retry_at=CASE WHEN %s::integer IS NULL THEN NULL ELSE clock_timestamp()+%s*interval '1 second' END,
             last_error_code=%s,last_error_at=CASE WHEN %s THEN clock_timestamp() ELSE NULL END,
             delivered_at=CASE WHEN %s='Delivered' THEN clock_timestamp() ELSE NULL END
             WHERE delivery_id=%s AND lease_token=%s AND lease_until>clock_timestamp() RETURNING delivery_id""",
             (status,delay,delay,error.code if error else None,error is not None,status,delivery["delivery_id"],delivery["lease_token"])).fetchone()
            if not r:raise LeaseLost()
