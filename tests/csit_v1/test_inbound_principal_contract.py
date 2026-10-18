import time
from dataclasses import replace
from types import SimpleNamespace
import jwt,pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.auth import JwtServiceTokenValidator
from src.csit_integration_v1.api import create_app

@pytest.fixture(scope='module')
def signing_key():return rsa.generate_private_key(public_exponent=65537,key_size=2048)
@pytest.fixture
def inbound_settings(tmp_path):
    secret=tmp_path/'outbound-test-secret';secret.write_text('test-only');secret.chmod(0o600)
    return Settings(enabled=True,db_url='postgresql://user:dummy@fixture.invalid/db',
      authority='https://issuer.invalid/',audience='km.integration.dev',outbound_audience='csit.integration.dev',
      jwks_uri='https://issuer.invalid/jwks',token_url='https://issuer.invalid/token',client_id='km-csit-integration-dev',
      secret_file=str(secret),service_clients=('csit-km-ingestion-dev',),service_claim='principal_type',service_claim_value='service',
      csit_base_url='https://csit.invalid',storage_root=str(tmp_path))
def make_token(s,key,mutation=None):
    c={'iss':s.authority,'aud':s.audience,'iat':int(time.time()),'exp':int(time.time())+300,
       'sub':'csit-km-ingestion-dev','client_id':'csit-km-ingestion-dev','principal_type':'service','scope':'km.ingestion.submit'}
    for k,v in (mutation or {}).items():
        if v is None:c.pop(k,None)
        else:c[k]=v
    return jwt.encode(c,key,algorithm='RS256',headers={'kid':'fixture-key'})
def validator(s,key):
    v=JwtServiceTokenValidator(s)
    v.keys=SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=key.public_key()))
    return v
class NoSubmitRepo:
    def __init__(self):self.submissions=0
    def submit(self,*args):self.submissions+=1;raise AssertionError('invalid auth/body must never submit a job')

def test_signed_known_good_contract_reproduces_legacy_gty_401(inbound_settings,signing_key):
    s=inbound_settings;token=make_token(s,signing_key)
    claims=jwt.decode(token,signing_key.public_key(),algorithms=['RS256'],issuer=s.authority,audience=s.audience)
    assert claims['principal_type']=='service' and 'gty' not in claims
    old=replace(s,service_claim='gty',service_claim_value='client_credentials')
    with pytest.raises(HTTPException) as ex:validator(old,signing_key).validate(token)
    assert ex.value.status_code==401
    assert validator(s,signing_key).validate(token).client_id=='csit-km-ingestion-dev'

@pytest.mark.parametrize('mutation,status',[
 ({},422),({'scope':'unrelated.scope'},403),({'client_id':'km-dev'},401),
 ({'principal_type':'human','gty':'client_credentials'},401),({'principal_type':None},401),
 ({'aud':'csit.integration.dev'},401),({'iss':'https://issuer.invalid'},401),
 ({'exp':1},401),({'nbf':int(time.time())+3600},401),({'iat':int(time.time())+3600},401)])
def test_service_auth_invalid_schema_probe_and_negative_contract(inbound_settings,signing_key,mutation,status):
    repo=NoSubmitRepo();app=create_app(inbound_settings,repo,validator(inbound_settings,signing_key))
    with TestClient(app) as c:
        r=c.post('/api/integrations/csit/v1/ingestion-jobs',json={},headers={'Authorization':'Bearer '+make_token(inbound_settings,signing_key,mutation)})
    assert r.status_code==status and repo.submissions==0

def test_invalid_signature_no_principal_or_job(inbound_settings,signing_key):
    other=rsa.generate_private_key(public_exponent=65537,key_size=2048);repo=NoSubmitRepo()
    app=create_app(inbound_settings,repo,validator(inbound_settings,signing_key))
    with TestClient(app) as c:r=c.post('/api/integrations/csit/v1/ingestion-jobs',json={},headers={'Authorization':'Bearer '+make_token(inbound_settings,other)})
    assert r.status_code==401 and repo.submissions==0
