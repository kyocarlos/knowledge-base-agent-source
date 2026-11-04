"""Inbound CSIT -> KM routes of spec v1.3. Disabled (503) until KM_CSIT_DOCLIB_ENABLED=true."""
import uuid
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError, BaseModel
from .auth import authorize
from .errors import IntegrationError
from .doclib_models import DocLibRequest, DocLibAccepted, DeletionRequest, DeletionAccepted

JOBS_ROUTE='/api/integrations/csit/v1/document-library/jobs'
DELETIONS_ROUTE='/api/integrations/csit/v1/document-deletions'
MAX_BODY=65536

def _errors(exc):
    # Field path, type and constraint only; never the received value.
    return [{'field':'.'.join(str(x) for x in e['loc']) or 'body','type':e['type'],'expected':e['msg']}
            for e in exc.errors(include_url=False,include_context=False,include_input=False)[:32]]

async def _body(request,model):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_BODY:raise HTTPException(413,'Contract payload exceeds limit')
    try:return model.model_validate_json(bytes(raw))
    except ValidationError as exc:
        raise HTTPException(422,{'code':'INVALID_CSIT_CONTRACT','errors':_errors(exc)}) from None

def _idempotency(request,expected):
    key=request.headers.get('idempotency-key')
    if key is None:return # CSIT sends it; the body id is authoritative, so a missing header is tolerated
    try:ok=uuid.UUID(key)==expected
    except ValueError:ok=False
    if not ok:raise HTTPException(400,{'code':'IDEMPOTENCY_KEY_MISMATCH','message':'Idempotency-Key must equal the body id'})

def register(app:FastAPI,settings,repo,get_validator):
    @app.post(JOBS_ROUTE,status_code=202,response_model=DocLibAccepted)
    async def doclib_jobs(request:Request):
        authorize(request,get_validator())
        payload=await _body(request,DocLibRequest)
        _idempotency(request,payload.csitJobId)
        if payload.file.fileSizeBytes>settings.max_file_size:
            raise HTTPException(422,{'code':'INVALID_CSIT_CONTRACT','errors':[{'field':'file.fileSizeBytes','type':'configured_size_limit','expected':'at most '+str(settings.max_file_size)+' bytes'}]})
        if not settings.doclib_enabled:raise HTTPException(503,'Document-library integration disabled; no jobs accepted')
        try:row=repo.submit(payload)
        except IntegrationError as e:raise HTTPException(409,{'code':e.code,'message':e.message}) from None
        except Exception:raise HTTPException(503,'Metadata DB unavailable') from None
        return DocLibAccepted(csitJobId=row['csit_job_id'],kmJobId=row['km_job_id'])
    @app.post(DELETIONS_ROUTE,status_code=202,response_model=DeletionAccepted)
    async def document_deletions(request:Request):
        authorize(request,get_validator())
        payload=await _body(request,DeletionRequest)
        _idempotency(request,payload.deletionRequestId)
        if not settings.doclib_enabled:raise HTTPException(503,'Deletion integration disabled; no requests accepted')
        try:row=repo.submit_deletion(payload)
        except IntegrationError as e:raise HTTPException(409,{'code':e.code,'message':e.message}) from None
        except Exception:raise HTTPException(503,'Metadata DB unavailable') from None
        return DeletionAccepted(deletionRequestId=row['deletion_request_id'],kmDeletionJobId=row['km_deletion_job_id'])
