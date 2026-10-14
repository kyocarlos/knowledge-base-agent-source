import json,uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
import pytest
from src.csit_integration_v1.models import IngestionRequest
from src.csit_integration_v1.errors import IntegrationError
from src.csit_integration_v1.api import ROUTE

REASON='CSIT 7444 service authorization root cause corrected and verified by document HTTP 200 and callback validation HTTP 400.'
@pytest.fixture
def terminal(repo,payload):
    actor=str(uuid.uuid4())
    with repo.connect() as c:c.execute("INSERT INTO km_users(user_id,status,is_admin) VALUES(%s,'active',true)",(actor,))
    row=repo.submit(IngestionRequest(**payload));job=repo.claim('prior-worker',60)
    repo.fail(job,IntegrationError('CSIT_AUTH_FORBIDDEN','CSIT service authorization rejected'),(0,))
    with repo.connect() as c:
        c.execute("UPDATE km_csit_callback_deliveries SET status='Failed',attempt_count=1,last_error_code='CSIT_AUTH_FORBIDDEN',last_error_at=clock_timestamp() WHERE job_id=%s",(row['job_id'],))
    old=repo.get(row['job_id'])
    identity={k:old[k] for k in ['event_id','source_system','document_id','version']}
    return old,identity,actor

def resume(repo,t,**changes):
    old,identity,actor=t
    return repo.resume(old['job_id'],changes.get('identity',identity),changes.get('actor',actor),'fixture-operator',changes.get('reason',REASON))

def test_same_job_identity_history_audit_and_normal_claim(repo,terminal):
    old,identity,actor=terminal;r=resume(repo,terminal)
    assert r['job']['jobId']==str(old['job_id']) and r['job']['status']=='Accepted'
    updated=repo.get(old['job_id'])
    assert all(updated[k]==old[k] for k in ['job_id','event_id','source_system','document_id','version','attempt_count','last_error_code','last_error_at'])
    with repo.connect() as c:
        assert c.execute('SELECT count(*) AS n FROM km_csit_ingestion_jobs').fetchone()['n']==1
        audit=c.execute('SELECT * FROM km_audit_events').fetchone()
        details=json.loads(audit['detail_json'])
        assert audit['actor_user_id']==actor and audit['event_type']=='csit_job_resumed'
        assert details['previous']['attempt_count']==1 and details['previous']['last_error_code']=='CSIT_AUTH_FORBIDDEN'
        assert details['previous']['last_error_at']==old['last_error_at'].isoformat() or details['previous']['last_error_at']==str(old['last_error_at'])
        assert len(details['previous_callbacks'])==2 and details['resulting_status']=='Accepted'
    claimed=repo.claim('normal-worker',60)
    assert claimed['job_id']==old['job_id'] and claimed['status']=='Processing'
    assert claimed['attempt_count']==2 and claimed['_resume_attempt_base']==1
    repo.finish(claimed,{},'parser-test','extraction-test')
    with repo.connect() as c:
        assert c.execute('SELECT count(*) AS n FROM km_audit_events').fetchone()['n']==1
        assert json.loads(c.execute('SELECT detail_json FROM km_audit_events').fetchone()['detail_json'])['previous']['last_error_code']=='CSIT_AUTH_FORBIDDEN'

@pytest.mark.parametrize('status',['Accepted','Processing','Completed'])
def test_non_failed_status_rejected(repo,terminal,status):
    with repo.connect() as c:c.execute('UPDATE km_csit_ingestion_jobs SET status=%s WHERE job_id=%s',(status,terminal[0]['job_id']))
    with pytest.raises(IntegrationError,match='RESUME_TERMINAL_FAILED_REQUIRED'):resume(repo,terminal)

@pytest.mark.parametrize('lease_field',['lease_token','lease_until'])
def test_any_lease_rejected(repo,terminal,lease_field):
    with repo.connect() as c:
        if lease_field=='lease_token':c.execute('UPDATE km_csit_ingestion_jobs SET lease_token=%s WHERE job_id=%s',(uuid.uuid4(),terminal[0]['job_id']))
        else:c.execute("UPDATE km_csit_ingestion_jobs SET lease_until=clock_timestamp()+interval '1 hour' WHERE job_id=%s",(terminal[0]['job_id'],))
    with pytest.raises(IntegrationError,match='RESUME_LEASE_ACTIVE'):resume(repo,terminal)

def test_scheduled_failed_retry_rejected(repo,terminal):
    with repo.connect() as c:c.execute('UPDATE km_csit_ingestion_jobs SET next_retry_at=clock_timestamp() WHERE job_id=%s',(terminal[0]['job_id'],))
    with pytest.raises(IntegrationError,match='RESUME_TERMINAL_FAILED_REQUIRED'):resume(repo,terminal)

@pytest.mark.parametrize('field,value',[('event_id','other'),('source_system','OTHER'),('document_id','other'),('version',99)])
def test_identity_mismatch_rejected(repo,terminal,field,value):
    identity=dict(terminal[1]);identity[field]=value
    with pytest.raises(IntegrationError,match='RESUME_IDENTITY_MISMATCH'):resume(repo,terminal,identity=identity)

def test_unknown_job_rejected(repo,terminal):
    with pytest.raises(IntegrationError,match='RESUME_JOB_NOT_FOUND'):
        repo.resume(uuid.uuid4(),terminal[1],terminal[2],'fixture-operator',REASON)

@pytest.mark.parametrize('role,status',[(False,'active'),(True,'disabled')])
def test_existing_admin_gate_rejects_non_admin_or_disabled(repo,terminal,role,status):
    with repo.connect() as c:c.execute('UPDATE km_users SET is_admin=%s,status=%s WHERE user_id=%s',(role,status,terminal[2]))
    with pytest.raises(IntegrationError,match='RESUME_ADMIN_REQUIRED'):resume(repo,terminal)

def test_unknown_actor_rejected(repo,terminal):
    with pytest.raises(IntegrationError,match='RESUME_ADMIN_REQUIRED'):resume(repo,terminal,actor=str(uuid.uuid4()))

def test_concurrent_resume_exactly_one_success(repo,terminal):
    def perform(_):
        try:resume(repo,terminal);return True
        except IntegrationError:return False
    with ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(perform,range(8)))
    assert sum(results)==1
    with repo.connect() as c:assert c.execute('SELECT count(*) AS n FROM km_audit_events').fetchone()['n']==1

def test_active_callback_rejected(repo,terminal):
    with repo.connect() as c:c.execute("UPDATE km_csit_callback_deliveries SET status='Pending' WHERE job_id=%s",(terminal[0]['job_id'],))
    with pytest.raises(IntegrationError,match='RESUME_CALLBACK_ACTIVE'):resume(repo,terminal)

def test_ingestion_duplicate_failed_does_not_resume(api,repo,payload,terminal):
    r=api.post(ROUTE,json=payload,headers={'Authorization':'Bearer test-service'})
    assert r.status_code==202 and r.json()['jobId']==str(terminal[0]['job_id']) and r.json()['status']=='Failed'
    with repo.connect() as c:assert c.execute('SELECT count(*) AS n FROM km_audit_events').fetchone()['n']==0

def test_resume_restarts_retry_budget_without_erasing_lifetime_count(repo,terminal):
    with repo.connect() as c:c.execute('UPDATE km_csit_ingestion_jobs SET attempt_count=10 WHERE job_id=%s',(terminal[0]['job_id'],))
    resume(repo,terminal);job=repo.claim('worker',60)
    assert job['attempt_count']==11 and job['_resume_attempt_base']==10
    repo.fail(job,IntegrationError('TEMPORARY','Temporary writer failure',True),(10,20))
    assert repo.get(job['job_id'])['next_retry_at'] is not None

@pytest.mark.parametrize('reason',['','line\nline','Bearer PRIVATE','Authorization: secret'])
def test_reason_rejects_credentials_or_unbounded_input(repo,terminal,reason):
    with pytest.raises(IntegrationError,match='RESUME_REASON_INVALID'):resume(repo,terminal,reason=reason)
