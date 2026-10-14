import copy,json,uuid
from pathlib import Path
from datetime import datetime,timezone
import pytest
from src.csit_integration_v1.models import IngestionRequest
from src.csit_integration_v1.errors import IntegrationError

HISTORICAL=Path(__file__).parent/'fixtures/processing-callback-20261014.json'
def processing_contract(p):
    assert uuid.UUID(p['jobId']) and uuid.UUID(p['documentId'])
    assert p['status']=='Processing' and p['sourceSystem']=='CSIT'
    assert type(p['version']) is int and p['version']>=1
    if not isinstance(p.get('timestamps'),dict) or 'startedAt' not in p['timestamps']:
        raise ValueError('timestamps.startedAt MISSING')
    value=p['timestamps']['startedAt']
    if not isinstance(value,str):raise ValueError('timestamps.startedAt INVALID')
    datetime.fromisoformat(value.replace('Z','+00:00'))

def test_saved_historical_body_proves_missing_started_at():
    historical=json.loads(HISTORICAL.read_text())
    assert historical['timestamps']=={'updatedAt':'2026-10-14T03:13:15.784489+00:00'}
    assert 'error' not in historical
    with pytest.raises(ValueError,match='timestamps.startedAt MISSING'):processing_contract(historical)

@pytest.mark.parametrize('value',[None,'not-a-time',17])
def test_processing_contract_rejects_invalid_started_at(value):
    p=json.loads(HISTORICAL.read_text());p['timestamps']['startedAt']=value
    with pytest.raises((ValueError,TypeError)):processing_contract(p)

@pytest.mark.parametrize('alias',['processingAt','started_at','startAt','StartedAt'])
def test_processing_contract_requires_exact_json_property(alias):
    p=json.loads(HISTORICAL.read_text());p['timestamps'][alias]=p['timestamps']['updatedAt']
    with pytest.raises(ValueError,match='MISSING'):processing_contract(p)

def stored_callback(repo,job,status):
    with repo.connect() as c:
        return c.execute("SELECT payload FROM km_csit_callback_deliveries WHERE job_id=%s AND payload->>'status'=%s ORDER BY sequence DESC LIMIT 1",(job['job_id'],status)).fetchone()['payload']

def test_normal_claim_produces_required_nested_started_at(repo,payload):
    request=IngestionRequest(**payload);repo.submit(request);job=repo.claim('test-worker',60)
    p=stored_callback(repo,job,'Processing')
    assert p['status']=='Processing' and p['timestamps']=={'updatedAt':job['updated_at'].isoformat(),'startedAt':job['updated_at'].isoformat()}
    assert 'startedAt' not in p and 'error' not in p
    assert not {'processingAt','started_at','startAt','StartedAt'}&set(p['timestamps'])
    assert datetime.fromisoformat(p['timestamps']['startedAt']).tzinfo is not None
    # Contract identities in the regular fixture can be non-UUID text; shape checks are separate.
    assert all(p[k]==payload[k] for k in ['sourceSystem','documentId','version'])

def test_current_processing_transition_used_even_when_original_start_is_older(repo,payload):
    r=repo.submit(IngestionRequest(**payload))
    with repo.connect() as c:c.execute('UPDATE km_csit_ingestion_jobs SET started_at=%s WHERE job_id=%s',(datetime(2020,1,1,tzinfo=timezone.utc),r['job_id']))
    job=repo.claim('test-worker',60);p=stored_callback(repo,job,'Processing')
    assert datetime.fromisoformat(p['timestamps']['startedAt'])==job['updated_at']
    assert datetime.fromisoformat(p['timestamps']['startedAt'])!=job['started_at']

def test_completed_branch_exact_original_behavior(repo,payload):
    repo.submit(IngestionRequest(**payload));job=repo.claim('test-worker',60)
    repo.finish(job,{},'test-parser','test-extraction');r=repo.get(job['job_id']);p=stored_callback(repo,job,'Completed')
    assert p=={'jobId':str(job['job_id']),'sourceSystem':'CSIT','documentId':payload['documentId'],'version':payload['version'],'status':'Completed','timestamps':{'updatedAt':r['updated_at'].isoformat(),'completedAt':r['completed_at'].isoformat()}}
    assert 'startedAt' not in p['timestamps']

def test_failed_branch_unchanged_per_explicit_scope_decision(repo,payload):
    repo.submit(IngestionRequest(**payload));job=repo.claim('test-worker',60)
    repo.fail(job,IntegrationError('SOURCE_ERROR','Sanitized test error'),());r=repo.get(job['job_id']);p=stored_callback(repo,job,'Failed')
    assert p=={'jobId':str(job['job_id']),'sourceSystem':'CSIT','documentId':payload['documentId'],'version':payload['version'],'status':'Failed','timestamps':{'updatedAt':r['updated_at'].isoformat()},'error':{'code':'SOURCE_ERROR','message':'Sanitized test error'}}
    assert 'failedAt' not in p['timestamps']  # Known pre-existing gap, deferred by the user.
