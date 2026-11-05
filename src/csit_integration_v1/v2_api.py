"""Inbound CSIT -> KM routes of spec v1.4. Disabled (503) until KM_CSIT_DOCLIB_ENABLED=true, like the v1.3 routes."""
import uuid
from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError
from .auth import authorize, SUBMIT_SCOPE
from .errors import IntegrationError
from .v2_models import (DocumentJobRequest, DocumentJobAccepted, MetadataChangeRequest, MetadataChangeAccepted,
                        V2DeletionRequest, V2DeletionAccepted)

JOBS_ROUTE='/api/integrations/csit/v2/document-jobs'
CHANGES_ROUTE='/api/integrations/csit/v2/document-metadata-changes'
DELETIONS_ROUTE='/api/integrations/csit/v2/document-deletions'
MAX_BODY=262144
# Spec 3.2 suggests exact scopes per direction; the v1.3 scope stays accepted until CSIT IT confirms the mapping.
SCOPES={'jobs':{SUBMIT_SCOPE,'km.ingestion.write'},'changes':{SUBMIT_SCOPE,'km.metadata.write'},'deletions':{SUBMIT_SCOPE,'km.deletion.write'}}
# Spec 3.3: tombstoned/unknown sources are 410/404, everything else a conflict.
STATUS={'DOCUMENT_DELETED':410,'DOCUMENT_NOT_FOUND':404}

def _errors(exc):
    # Field path, type and constraint only; never the received value.
    return [{'field':'.'.join(str(x) for x in e['loc']) or 'body','type':e['type'],'expected':e['msg']}
            for e in exc.errors(include_url=False,include_context=False,include_input=False)[:32]]

async def _body(request,model):
    if not request.headers.get('content-type','').lower().startswith('application/json'):
        raise HTTPException(415,'Request Content-Type must be application/json')
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_BODY:raise HTTPException(413,'Contract payload exceeds limit')
    try:return model.model_validate_json(bytes(raw))
    except ValidationError as exc:
        raise HTTPException(400,{'code':'INVALID_CSIT_CONTRACT','errors':_errors(exc)}) from None

def _idempotency(request,expected):
    key=request.headers.get('idempotency-key')
    if key is None:return # the body id is authoritative; CSIT sends the header
    try:ok=uuid.UUID(key)==expected
    except ValueError:ok=False
    if not ok:raise HTTPException(400,{'code':'IDEMPOTENCY_KEY_MISMATCH','message':'Idempotency-Key must equal the body id'})

def _call(fn,*args):
    try:return fn(*args)
    except IntegrationError as e:raise HTTPException(STATUS.get(e.code,409),{'code':e.code,'message':e.message}) from None
    except HTTPException:raise
    except Exception:raise HTTPException(503,'Metadata DB unavailable') from None

def register(app:FastAPI,settings,repo,get_validator):
    @app.post(JOBS_ROUTE,status_code=202,response_model=DocumentJobAccepted)
    async def document_jobs(request:Request):
        authorize(request,get_validator(),SCOPES['jobs'])
        payload=await _body(request,DocumentJobRequest)
        _idempotency(request,payload.eventId)
        if not settings.doclib_enabled:raise HTTPException(503,'Document integration disabled; no jobs accepted')
        row=_call(repo.submit_job,payload)
        return DocumentJobAccepted(eventId=row['event_id'],csitJobId=row['csit_job_id'],kmJobId=row['km_job_id'])
    @app.post(CHANGES_ROUTE,status_code=202,response_model=MetadataChangeAccepted)
    async def metadata_changes(request:Request):
        authorize(request,get_validator(),SCOPES['changes'])
        payload=await _body(request,MetadataChangeRequest)
        _idempotency(request,payload.changeId)
        if not settings.doclib_enabled:raise HTTPException(503,'Document integration disabled; no changes accepted')
        row=_call(repo.submit_change,payload)
        return MetadataChangeAccepted(changeId=row['change_id'],kmChangeJobId=row['km_change_job_id'])
    @app.post(DELETIONS_ROUTE,status_code=202,response_model=V2DeletionAccepted)
    async def document_deletions(request:Request):
        authorize(request,get_validator(),SCOPES['deletions'])
        payload=await _body(request,V2DeletionRequest)
        _idempotency(request,payload.deletionRequestId)
        if not settings.doclib_enabled:raise HTTPException(503,'Deletion integration disabled; no requests accepted')
        row=_call(repo.submit_deletion_v2,payload)
        return V2DeletionAccepted(deletionRequestId=row['deletion_request_id'],kmDeletionJobId=row['km_deletion_job_id'])
