import copy,json
from dataclasses import replace
from types import SimpleNamespace
import jwt,pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from src.csit_integration_v1.models import IngestionRequest
from src.csit_integration_v1.api import create_app,ROUTE
from test_inbound_principal_contract import inbound_settings,signing_key,make_token,NoSubmitRepo

@pytest.mark.parametrize('ref',['project','case','task'])
def test_number_required_no_legacy_code_alias(payload,ref):
    p=copy.deepcopy(payload);p[ref]['code']=p[ref].pop('number')
    with pytest.raises(ValidationError) as e:IngestionRequest.model_validate(p)
    errors={(tuple(x['loc']),x['type']) for x in e.value.errors()}
    assert ((ref,'number'),'missing') in errors
    assert ((ref,'code'),'extra_forbidden') in errors

@pytest.mark.parametrize('ref',['project','case','task'])
@pytest.mark.parametrize('value',[12,True])
def test_reference_number_rejects_non_string_value(payload,ref,value):
    p=copy.deepcopy(payload);p[ref]['number']=value
    with pytest.raises(ValidationError):IngestionRequest.model_validate(p)

@pytest.mark.parametrize('ref',['project','case','task','document'])
def test_nested_extras_remain_forbidden(payload,ref):
    p=copy.deepcopy(payload);p[ref]['unknown']='forbidden'
    with pytest.raises(ValidationError):IngestionRequest.model_validate(p)

@pytest.mark.parametrize('value',[None,12,True,{}])
def test_non_string_filename_is_validation_error(payload,value):
    p=copy.deepcopy(payload);p['document']['fileName']=value
    with pytest.raises(ValidationError):IngestionRequest.model_validate(p)

def test_number_persisted_in_existing_lineage_columns(repo,payload):
    job=repo.submit(IngestionRequest.model_validate(payload))
    for ref in ['project','case','task']:
        assert job[ref+'_code']==payload[ref]['number']
        assert job['request_payload'][ref]['number']==payload[ref]['number']
        assert 'code' not in job['request_payload'][ref]

def disabled_client(s,key,monkeypatch):
    monkeypatch.setattr(jwt.PyJWKClient,'get_signing_key_from_jwt',lambda _,tok:SimpleNamespace(key=key.public_key()))
    repo=NoSubmitRepo();client=TestClient(create_app(replace(s,enabled=False),repo))
    return client,repo,make_token(s,key)

def test_canonical_signed_request_disabled_503_zero_submit(inbound_settings,signing_key,monkeypatch,payload,caplog):
    client,repo,token=disabled_client(inbound_settings,signing_key,monkeypatch)
    payload['eventId']='538a9cbf-1361-4475-867e-d8db7dcf57d1'
    payload['documentId']='4e805899-97a8-44b0-a6e0-8b1779da931d'
    with client:r=client.post(ROUTE,json=payload,headers={'Authorization':'Bearer '+token,'Idempotency-Key':payload['eventId']})
    assert r.status_code==503 and repo.submissions==0
    e=[json.loads(x.message) for x in caplog.records if x.name=='km.csit.integration.auth'][-1]
    assert e['schema_validation']=='PASS' and e['event_id']==payload['eventId'] and e['document_id']==payload['documentId']
    assert e['endpoint_authorization']=='PASS' and e['http_status']==503
    assert token not in caplog.text and payload['document']['fileName'] not in caplog.text

def test_validation_details_exclude_values_and_arbitrary_keys(inbound_settings,signing_key,monkeypatch,payload,caplog):
    client,repo,token=disabled_client(inbound_settings,signing_key,monkeypatch)
    private='DO_NOT_LOG_PRIVATE_PAYLOAD_VALUE'
    payload['project']['code']=payload['project'].pop('number')
    payload['task'][private]=private
    payload['document']['fileName']=private
    with client:r=client.post(ROUTE,json=payload,headers={'Authorization':'Bearer '+token})
    assert r.status_code==422 and repo.submissions==0
    errors=r.json()['detail']['errors']
    assert any(x['field']=='project.number' and x['type']=='missing' for x in errors)
    assert any(x['field']=='project.code' and x['type']=='extra_forbidden' for x in errors)
    assert any(x['field']=='task.<extra>' for x in errors)
    assert private not in caplog.text+r.text and token not in caplog.text+r.text

def test_configured_file_limit_remains_schema_gate(inbound_settings,signing_key,monkeypatch,payload):
    client,repo,token=disabled_client(replace(inbound_settings,max_file_size=1),signing_key,monkeypatch)
    with client:r=client.post(ROUTE,json=payload,headers={'Authorization':'Bearer '+token})
    assert r.status_code==422 and repo.submissions==0
    assert r.json()['detail']['errors'][0]['field']=='document.sizeBytes'


def test_reference_empty_string_allowed_by_wire_contract(payload):
    payload['project']['number']=''
    payload['project']['name']=''
    parsed=IngestionRequest.model_validate(payload)
    assert parsed.project.number=='' and parsed.project.name==''

def test_null_reference_metadata_survives_request_and_repository(repo,payload):
    for ref in ('project','case','task'):
        payload[ref]['number']=None
        payload[ref]['name']=None
    request=IngestionRequest.model_validate(payload)
    assert request.model_dump(mode='json')['project']['number'] is None
    row=repo.submit(request)
    assert row['request_payload']['project']['number'] is None
    assert row['request_payload']['project']['name'] is None
    for ref in ('project','case','task'):
        assert row[ref+'_code'] is None and row[ref+'_name'] is None
        assert row['request_payload'][ref]['number'] is None
        assert row['request_payload'][ref]['name'] is None
