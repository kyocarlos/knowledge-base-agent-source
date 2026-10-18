import base64,json,time
from dataclasses import replace
from types import SimpleNamespace
from urllib.parse import parse_qs
import httpx,jwt,pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from src.csit_integration_v1.config import Settings
from src.csit_integration_v1.auth import ClientCredentialsProvider,OUTBOUND_SCOPES
from src.csit_integration_v1.errors import IntegrationError

@pytest.fixture(scope='module')
def key():return rsa.generate_private_key(public_exponent=65537,key_size=2048)
@pytest.fixture
def outbound_settings(tmp_path):
    p=tmp_path/'service';p.write_text('test-only-secret');p.chmod(0o600)
    return Settings(enabled=False,authority='https://issuer.invalid/',audience='km.integration.dev',
        outbound_audience='csit.integration.dev',jwks_uri='https://issuer.invalid/jwks',
        token_url='https://issuer.invalid/token',client_id='km-csit-integration-dev',secret_file=str(p))
def signed(s,key,mutation=None):
    c={'iss':s.authority,'aud':s.outbound_audience,'iat':int(time.time()),'exp':int(time.time())+300,
        'sub':s.client_id,'client_id':s.client_id,'principal_type':'service','scope':' '.join(OUTBOUND_SCOPES)}
    for k,v in (mutation or {}).items():
        if v is None:c.pop(k,None)
        else:c[k]=v
    return jwt.encode(c,key,algorithm='RS256')
def make(s,key,token,extra=None):
    calls=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(200,json=dict(access_token=token,token_type='Bearer',expires_in=300,**(extra or {})))
    p=ClientCredentialsProvider(s,httpx.MockTransport(handler))
    p.keys=SimpleNamespace(get_signing_key_from_jwt=lambda _:SimpleNamespace(key=key.public_key()))
    return p,calls

@pytest.mark.parametrize('extra',[{}, {'scope':' '.join(OUTBOUND_SCOPES)}])
def test_request_contract_cache_optional_response_scope(outbound_settings,key,extra):
    s=outbound_settings;token=signed(s,key);p,calls=make(s,key,token,extra)
    assert p.headers()==p.headers() and len(calls)==1
    r=calls[0];form=parse_qs(r.content.decode())
    assert set(form)=={'grant_type','scope'}
    assert form['grant_type']==['client_credentials'] and form['scope']==[' '.join(OUTBOUND_SCOPES)]
    assert r.headers['authorization']=='Basic '+base64.b64encode((s.client_id+':test-only-secret').encode()).decode()
    assert 'audience' not in form and 'resource' not in form
    assert s.audience!=s.outbound_audience
    p.close();assert p._token is None

@pytest.mark.parametrize('mutation',[
    {'aud':'km.integration.dev'}, {'aud':['csit.integration.dev','other']}, {'iss':'https://wrong.invalid/'},
    {'exp':1},{'iat':int(time.time())+3600},{'principal_type':'human'},{'principal_type':None},
    {'sub':'km-dev'},{'client_id':'km-dev'},{'scope':'csit.document.read'},
    {'scope':' '.join(OUTBOUND_SCOPES)+' extra.privilege'},{'scope':None}, {'exp':None},{'iat':None}])
def test_signed_claims_fail_closed(outbound_settings,key,mutation):
    p,_=make(outbound_settings,key,signed(outbound_settings,key,mutation))
    with pytest.raises(IntegrationError):p.headers()
    assert p._token is None;p.close()
def test_signature_fail_closed(outbound_settings,key):
    other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    p,_=make(outbound_settings,key,signed(outbound_settings,other))
    with pytest.raises(IntegrationError,match='M2M_TOKEN_INVALID'):p.headers()
    assert p._token is None
@pytest.mark.parametrize('scope',['csit.document.read','',None, ['csit.document.read']])
def test_invalid_response_scope_fails(outbound_settings,key,scope):
    p,_=make(outbound_settings,key,signed(outbound_settings,key),{'scope':scope})
    with pytest.raises(IntegrationError,match='M2M_SCOPE_MISSING'):p.headers()
def test_outbound_audience_must_be_configured(outbound_settings,key):
    p,_=make(replace(outbound_settings,outbound_audience=''),key,signed(outbound_settings,key))
    with pytest.raises(IntegrationError,match='M2M_TOKEN_INVALID'):p.headers()
@pytest.mark.parametrize('status,code',[(400,'M2M_UNAVAILABLE'),(401,'M2M_AUTH_FAILED'),(503,'M2M_UNAVAILABLE')])
def test_oauth_error_sanitized_and_not_logged(outbound_settings,status,code,capsys,caplog):
    s=outbound_settings;secret='test-only-secret';raw='test-only-raw-token'
    encoded=base64.b64encode((s.client_id+':'+secret).encode()).decode()
    r=httpx.Response(status,json={'error':'invalid_request','error_description':secret+' Basic '+encoded+' Bearer '+raw,'access_token':raw})
    p=ClientCredentialsProvider(s,httpx.MockTransport(lambda _:r))
    with pytest.raises(IntegrationError,match=code) as ex:p.headers()
    text=json.dumps(ex.value.diagnostic)+str(ex.value)+ex.value.message
    assert secret not in text and encoded not in text and raw not in text
    assert ex.value.diagnostic['http_status']==status and ex.value.diagnostic['oauth_error']=='invalid_request'
    assert not capsys.readouterr().out and not caplog.records
    p.close()
def test_transport_error_not_leaked(outbound_settings,capsys):
    def fail(r):raise httpx.ConnectError('test-only-secret Bearer test-only-token',request=r)
    p=ClientCredentialsProvider(outbound_settings,httpx.MockTransport(fail))
    with pytest.raises(IntegrationError,match='M2M_UNAVAILABLE') as e:p.headers()
    assert e.value.__cause__ is None and 'test-only' not in str(e.value)
    assert not capsys.readouterr().out
