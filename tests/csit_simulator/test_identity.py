"""The simulator as identity authority: KM's own M2M code (token request + JWKS validation, inbound validation) must accept it over HTTPS."""
import socket,threading,time
import pytest

pytest.importorskip("jwt");pytest.importorskip("cryptography")
import uvicorn
from tools.csit_simulator.app import create_app
from tools.csit_simulator.identity import Identity,OUTBOUND_SCOPES,SUBMIT_SCOPE
from tools.csit_simulator.sim import Sim
from tools.csit_simulator.tls import ensure

def free_port():
    with socket.socket() as s:s.bind(("127.0.0.1",0));return s.getsockname()[1]

@pytest.fixture
def idp(tmp_path,monkeypatch):
    port=free_port();base=f"https://localhost:{port}"
    files=ensure(tmp_path/"tls",["localhost"])
    secret=tmp_path/"secret";secret.write_text("s3cret-value");secret.chmod(0o600)
    ident=Identity(base+"/","km.integration.sim","csit.integration.sim","km-csit-integration-sim","s3cret-value","csit-km-ingestion-sim",data_dir=tmp_path/"data")
    sim=Sim("http://127.0.0.1:1","unused",identity=ident)
    server=uvicorn.Server(uvicorn.Config(create_app(sim),host="127.0.0.1",port=port,ssl_certfile=str(files["server.pem"]),ssl_keyfile=str(files["server.key"]),log_level="error"))
    t=threading.Thread(target=server.run,daemon=True);t.start()
    for _ in range(100):
        try:socket.create_connection(("127.0.0.1",port),0.2).close();break
        except OSError:time.sleep(0.1)
    monkeypatch.setenv("SSL_CERT_FILE",str(files["ca.pem"]))
    from src.csit_integration_v1.config import Settings
    settings=Settings(enabled=True,csit_base_url=base,authority=base+"/",audience="km.integration.sim",outbound_audience="csit.integration.sim",jwks_uri=base+"/.well-known/jwks",
                      token_url=base+"/oauth/token",client_id="km-csit-integration-sim",secret_file=str(secret),service_clients=("csit-km-ingestion-sim",),
                      storage_root=str(tmp_path),db_url="postgresql://u@h/d")
    yield settings,ident,sim
    server.should_exit=True;t.join(5)

def test_kms_own_client_credentials_code_gets_and_validates_a_token_from_the_simulator(idp):
    from src.csit_integration_v1.auth import ClientCredentialsProvider
    settings,ident,_=idp
    provider=ClientCredentialsProvider(settings)
    try:header=provider.headers()["Authorization"]
    finally:provider.close()
    assert header.startswith("Bearer ")
    # the simulator accepts the token KM sends back, per route scope
    assert ident.verify_from_km(header,"csit.document.read") and ident.verify_from_km(header,"csit.ingestion.status.write")
    assert not ident.verify_from_km(header[:-3]+"abc") and not ident.verify_from_km("Bearer nope")

def test_kms_inbound_validator_accepts_the_token_the_simulator_signs(idp):
    from src.csit_integration_v1.auth import JwtServiceTokenValidator
    settings,ident,_=idp
    identity=JwtServiceTokenValidator(settings).validate(ident.mint_for_km())
    assert identity.client_id=="csit-km-ingestion-sim" and SUBMIT_SCOPE in identity.scopes

def test_a_wrong_client_secret_is_refused_and_the_secret_is_not_echoed(idp,tmp_path):
    from dataclasses import replace
    from src.csit_integration_v1.auth import ClientCredentialsProvider
    from src.csit_integration_v1.errors import IntegrationError
    settings,_,_=idp
    bad=tmp_path/"bad";bad.write_text("not-the-secret");bad.chmod(0o600)
    provider=ClientCredentialsProvider(replace(settings,secret_file=str(bad)))
    with pytest.raises(IntegrationError) as e:provider.headers()
    provider.close()
    assert e.value.code=="M2M_AUTH_FAILED" and "not-the-secret" not in str(e.value) and "s3cret-value" not in str(e.value)

def test_token_endpoint_rules(tmp_path):
    ident=Identity("https://x/","a","b","kc","sec","svc")
    import base64
    ok="Basic "+base64.b64encode(b"kc:sec").decode()
    assert ident.token_endpoint(ok,b"grant_type=client_credentials&scope=csit.document.read")[0]==200
    assert ident.token_endpoint(ok,b"grant_type=password")[0]==400
    assert ident.token_endpoint(ok,b"grant_type=client_credentials&scope=admin")[0]==400
    assert ident.token_endpoint("Basic "+base64.b64encode(b"kc:no").decode(),b"grant_type=client_credentials")[0]==401
    assert ident.token_endpoint("",b"grant_type=client_credentials")[0]==401
    status,body=ident.token_endpoint(ok,b"grant_type=client_credentials")
    assert set(body["scope"].split())==set(OUTBOUND_SCOPES)

def test_the_signing_key_survives_a_restart(tmp_path):
    a=Identity("https://x/","a","b","kc","sec","svc",data_dir=tmp_path)
    b=Identity("https://x/","a","b","kc","sec","svc",data_dir=tmp_path)
    assert a.kid==b.kid and a.jwks()==b.jwks()
