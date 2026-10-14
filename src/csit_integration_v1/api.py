from fastapi import FastAPI, Request, HTTPException
from .auth import authorize, JwtServiceTokenValidator
from .models import IngestionRequest, JobResponse
from .errors import IntegrationError
import json,logging,uuid
from pydantic import ValidationError
from datetime import datetime,timezone

ROUTE='/api/integrations/csit/v1/ingestion-jobs'
auth_logger=logging.getLogger('km.csit.integration.auth')
_CONTRACT_FIELDS=frozenset({'eventId','eventType','sourceSystem','documentId','version','project','case','task','document','committedAt','id','number','code','name','fileName','contentType','sizeBytes'})
def validation_errors(exc):
    # Keep field/type/constraint information, never input values or arbitrary JSON keys.
    result=[]
    for error in exc.errors(include_url=False,include_context=False)[:32]:
        path='.'.join(str(x) if x in _CONTRACT_FIELDS else '<extra>' for x in error['loc']) or 'body'
        value=error.get('input')
        received='missing' if error['type']=='missing' else type(value).__name__
        message='Invalid JSON' if error['type']=='json_invalid' else error['msg']
        result.append({'field':path,'type':error['type'],'expected':message,'received':received})
    return result

def request_metadata(raw):
    try:p=json.loads(raw)
    except (ValueError,TypeError):return {}
    if not isinstance(p,dict):return {}
    result={}
    for key,out in [('eventId','event_id'),('documentId','document_id')]:
        try:
            if isinstance(p.get(key),str):result[out]=str(uuid.UUID(p[key]))
        except ValueError:pass
    if type(p.get('version')) is int and 0<p['version']<=2147483647:result['version']=p['version']
    return result

def create_app(settings, repository, validator=None):
    settings.validate()
    app=FastAPI(title='KM CSIT Integration v1',docs_url=None,redoc_url=None)
    # Authentication remains active for harmless invalid-body probes while ingestion is disabled.
    inbound_ready=all((settings.authority,settings.audience,settings.jwks_uri,settings.service_clients))
    if validator is None and (settings.enabled or inbound_ready):
        settings.validate_inbound()
        validator=JwtServiceTokenValidator(settings)
    @app.middleware('http')
    async def auth_observation(request,call_next):
        if request.url.path!=ROUTE:return await call_next(request)
        trace=uuid.uuid4().hex
        timestamp=datetime.now(timezone.utc).isoformat()
        response=await call_next(request)
        evidence=getattr(request.state,'csit_auth_evidence',{})
        auth_logger.warning(json.dumps({'event':'csit_inbound_auth','trace_id':trace,'timestamp_utc':timestamp,
            'method':request.method,'path':ROUTE,**evidence,**getattr(request.state,'csit_validation_evidence',{}),'http_status':response.status_code,
            'www_authenticate':response.headers.get('www-authenticate')}))
        response.headers['X-CSIT-Auth-Trace']=trace
        return response
    @app.get('/health')
    def health():
        try:repository.check_schema()
        except Exception:raise HTTPException(503,'Metadata DB unavailable') from None
        return {'status':'ok','integrationEnabled':settings.enabled}
    @app.post(ROUTE,status_code=202,response_model=JobResponse)
    async def submit(request:Request):
        authorize(request,validator)
        try:
            raw=bytearray()
            async for chunk in request.stream():
                raw.extend(chunk)
                if len(raw)>65536:raise HTTPException(413,'Contract payload exceeds limit')
            payload=IngestionRequest.model_validate_json(bytes(raw))
        except HTTPException:raise
        except ValidationError as exc:
            errors=validation_errors(exc)
            request.state.csit_validation_evidence={'schema_validation':'FAIL','validation_errors':errors,**request_metadata(raw)}
            raise HTTPException(422,{'code':'INVALID_CSIT_CONTRACT','errors':errors}) from None
        request.state.csit_validation_evidence={'schema_validation':'PASS',**request_metadata(raw)}
        if payload.document.sizeBytes>settings.max_file_size:
            errors=[{'field':'document.sizeBytes','type':'configured_size_limit','expected':'at most '+str(settings.max_file_size)+' bytes','received':'above configured limit'}]
            request.state.csit_validation_evidence.update(schema_validation='FAIL',validation_errors=errors)
            raise HTTPException(422,{'code':'INVALID_CSIT_CONTRACT','errors':errors})
        # Hard gate before submit/DB mutation regardless of authentication or payload validity.
        if not settings.enabled:raise HTTPException(503,'Integration disabled; no ingestion jobs accepted')
        try:return repository.response(repository.submit(payload))
        except IntegrationError as e:raise HTTPException(409,{'code':e.code,'message':e.message}) from None
        except Exception:raise HTTPException(503,'Metadata DB unavailable') from None
    return app
