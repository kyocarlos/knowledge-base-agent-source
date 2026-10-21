from datetime import datetime,timezone
import uuid
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from src.csit_integration_v1.repository import Repository
from src.csit_integration_v1.errors import IntegrationError

class DevRepository(Repository):
    def __init__(self,db_url,schema):
        super().__init__(db_url)
        if not schema.replace("_","").isalnum():raise ValueError("invalid fixed schema")
        self.schema=schema
    def connect(self):
        # No public fallback: missing DEV schema cannot operate on CSIT tables.
        return psycopg.connect(self.db_url,row_factory=dict_row,options="-csearch_path="+self.schema)
    def _outbox(self,*args,**kwargs):pass
    def claim_callback(self,*args):return None
    def submit_payload(self,p):
        refs=[p[x][y] for x in ("project","case","task") for y in ("id","code","name")]
        with self.connect() as c:
            r=c.execute("""INSERT INTO km_csit_ingestion_jobs
            (job_id,event_id,source_system,event_type,document_id,version,
            project_id,project_code,project_name,case_id,case_code,case_name,task_id,task_code,task_name,
            file_name,content_type,size_bytes,committed_at,request_payload,status,content_sha256)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Accepted',%s)
            ON CONFLICT(source_system,document_id,version) DO NOTHING RETURNING *""",
            [uuid.uuid4(),p["eventId"],p["sourceSystem"],p["eventType"],p["documentId"],p["version"]]+refs+
            [p["document"]["fileName"],p["document"]["contentType"],p["document"]["sizeBytes"],
             p["committedAt"],Jsonb(p),p["uploadSha256"]]).fetchone()
            if r:return r,False
            r=c.execute("SELECT * FROM km_csit_ingestion_jobs WHERE source_system=%s AND document_id=%s AND version=%s",
                (p["sourceSystem"],p["documentId"],p["version"])).fetchone()
            old=dict(r["request_payload"]);new=dict(p)
            for k in ("eventId","committedAt","uploadReference"):
                old.pop(k,None);new.pop(k,None)
            if old!=new:raise IntegrationError("SOURCE_VERSION_CONFLICT","This test document/version already has different content or metadata")
            return r,True
    def owned(self,job_id,user_id):
        try:uuid.UUID(str(job_id))
        except (ValueError,TypeError):return None
        r=self.get(job_id)
        return r if r and r["request_payload"].get("ownerId")==user_id else None
    def list_owned(self,user_id,limit=30):
        with self.connect() as c:
            return c.execute("SELECT * FROM km_csit_ingestion_jobs WHERE request_payload->>'ownerId'=%s ORDER BY created_at DESC LIMIT %s",
                (user_id,limit)).fetchall()

def public_job(r,repo):
    p=r["request_payload"];checkpoints=repo.checkpoints(r)
    writers={name:{"status":"Completed" if name in checkpoints else
                ("NotApplicable" if r["status"]=="Completed" else "Pending")}
             for name in ("Storage","Qdrant","Neo4j","TimescaleDB")}
    return {"jobId":str(r["job_id"]),"sourceSystem":r["source_system"],"dataZone":p["dataZone"],
        "testRunId":p["testRunId"],"documentId":p["displayDocumentId"],"version":r["version"],
        "fileName":r["file_name"],"sha256":r["content_sha256"],"status":r["status"],"phase":r["phase"],
        "attemptCount":r["attempt_count"],"nextRetryAt":r["next_retry_at"].isoformat() if r["next_retry_at"] else None,
        "error":{"code":r["last_error_code"],"message":r["last_error_message"]} if r["last_error_code"] else None,
        "writers":writers,"parserVersion":r["parser_version"],"extractionVersion":r["extraction_version"],
        "updatedAt":r["updated_at"].isoformat(),"callbackEnabled":False}
