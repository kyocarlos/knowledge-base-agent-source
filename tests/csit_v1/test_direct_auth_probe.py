import json
from dataclasses import replace
from types import SimpleNamespace
import jwt,pytest
from fastapi.testclient import TestClient
from src.csit_integration_v1.api import create_app,ROUTE
from test_inbound_principal_contract import inbound_settings,signing_key,make_token,NoSubmitRepo

@pytest.mark.parametrize('body',[b'{}',b'{',b'{"probe":"auth-only"}'])
def test_disabled_auth_reaches_422_zero_submits(inbound_settings,signing_key,monkeypatch,caplog,body):
    s=replace(inbound_settings,enabled=False);repo=NoSubmitRepo()
    monkeypatch.setattr(jwt.PyJWKClient,'get_signing_key_from_jwt',lambda _,tok:SimpleNamespace(key=signing_key.public_key()))
    token=make_token(s,signing_key)
    with TestClient(create_app(s,repo)) as c:r=c.post(ROUTE,content=body,headers={'Authorization':'Bearer '+token})
    assert r.status_code==422 and repo.submissions==0
    events=[json.loads(r.message) for r in caplog.records if r.name=='km.csit.integration.auth']
    e=events[-1];assert e['authorization_header_present'] and e['jwt_principal_created']
    assert all(e[k]=='PASS' for k in ['signing_key','signature','issuer','audience','token_time','principal_type','service_identity','scope','endpoint_authorization'])
    assert e['trace_id']==r.headers['x-csit-auth-trace'] and e['http_status']==422
    assert token not in caplog.text and 'Authorization' not in caplog.text and 'auth-only' not in caplog.text

def test_disabled_valid_payload_cannot_create_job(inbound_settings,signing_key,monkeypatch,payload):
    s=replace(inbound_settings,enabled=False);repo=NoSubmitRepo()
    monkeypatch.setattr(jwt.PyJWKClient,'get_signing_key_from_jwt',lambda _,tok:SimpleNamespace(key=signing_key.public_key()))
    with TestClient(create_app(s,repo)) as c:r=c.post(ROUTE,json=payload,headers={'Authorization':'Bearer '+make_token(s,signing_key)})
    assert r.status_code==503 and repo.submissions==0

@pytest.mark.parametrize('mutation,code,status',[
 ({'aud':'csit.integration.dev'},'AUDIENCE_MISMATCH',401),
 ({'iss':'https://wrong.invalid/'},'ISSUER_MISMATCH',401),
 ({'exp':1},'TOKEN_EXPIRED',401),
 ({'principal_type':'human'},'SERVICE_MARKER_MISMATCH',401),
 ({'client_id':'km-dev'},'CLIENT_NOT_ALLOWED',401),
 ({'scope':'unrelated.scope'},'SUBMIT_SCOPE_MISSING',403)])
def test_safe_diagnostic_failure_stages(inbound_settings,signing_key,monkeypatch,caplog,mutation,code,status):
    s=replace(inbound_settings,enabled=False);repo=NoSubmitRepo()
    monkeypatch.setattr(jwt.PyJWKClient,'get_signing_key_from_jwt',lambda _,tok:SimpleNamespace(key=signing_key.public_key()))
    token=make_token(s,signing_key,mutation)
    with TestClient(create_app(s,repo)) as c:r=c.post(ROUTE,json={},headers={'Authorization':'Bearer '+token})
    assert r.status_code==status and repo.submissions==0
    e=[json.loads(r.message) for r in caplog.records if r.name=='km.csit.integration.auth'][-1]
    assert e['failure_check']==code and e['authorization_header_present']
    assert token not in caplog.text and 'test-only' not in caplog.text

def test_malformed_bearer_forwarding_diagnostic(inbound_settings,caplog):
    repo=NoSubmitRepo()
    with TestClient(create_app(replace(inbound_settings,enabled=False),repo)) as c:
        r=c.post(ROUTE,json={},headers={'Authorization':'Bearer not-a-jwt'})
    assert r.status_code==401 and repo.submissions==0
    e=[json.loads(r.message) for r in caplog.records if r.name=='km.csit.integration.auth'][-1]
    assert e['authorization_header_present'] and not e['jwt_principal_created']
    assert e['failure_check']=='JWT_FORMAT_INVALID' and 'not-a-jwt' not in caplog.text

def test_disabled_inbound_config_keeps_https_and_asymmetric_gate(inbound_settings):
    for s in [replace(inbound_settings,enabled=False,jwks_uri='http://unsafe.invalid/'),replace(inbound_settings,enabled=False,algorithm='HS256')]:
        with pytest.raises(ValueError):create_app(s,NoSubmitRepo())
