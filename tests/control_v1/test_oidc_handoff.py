import importlib.util,sys,os,tempfile,pathlib,unittest,time,base64,hashlib
from unittest.mock import patch,Mock
from urllib.parse import urlsplit,parse_qs
spec=importlib.util.spec_from_file_location("oidc_candidate",str(pathlib.Path(__file__).resolve().parents[2]/"src/oidc_control.py"))
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
BASE="https://csit-identity-dev.duckdns.org:7443"
ENV={"KM_OIDC_ENABLED":"true","KM_OIDC_ISSUER":BASE+"/","KM_OIDC_AUTHORIZATION_ENDPOINT":BASE+"/connect/authorize","KM_OIDC_TOKEN_ENDPOINT":BASE+"/connect/token","KM_OIDC_JWKS_URI":BASE+"/.well-known/jwks","KM_OIDC_CLIENT_ID":"km-dev","KM_OIDC_CLIENT_AUTH_METHOD":"client_secret_basic","KM_OIDC_REDIRECT_URI":"https://km-dev-da40.duckdns.org:3030/oidc/callback","KM_OIDC_POST_LOGOUT_REDIRECT_URI":"https://km-dev-da40.duckdns.org:3030/oidc/logout/callback"}
class OIDCTests(unittest.TestCase):
 def setUp(self):
  self.env=patch.dict(os.environ,ENV,clear=True);self.env.start()
  self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/"secret"
  self.path.write_text("unit-test-only-secret");self.path.chmod(0o600)
  os.environ["KM_OIDC_CLIENT_SECRET_FILE"]=str(self.path)
 def tearDown(self):self.env.stop();self.tmp.cleanup()
 def test_exact_issuer_and_PKCE(self):
  settings=m.OIDCSettings.from_environment();self.assertEqual(settings.issuer,BASE+"/")
  verifier="x"*64;url=settings.authorization_url("state-fixture","nonce-fixture",verifier)
  q=parse_qs(urlsplit(url).query)
  self.assertEqual(q["response_type"],["code"]);self.assertEqual(q["client_id"],["km-dev"])
  self.assertEqual(q["code_challenge_method"],["S256"])
  self.assertEqual(q["code_challenge"],[base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")])
  self.assertNotIn(self.path.read_text(),url)
 def test_file_priority_and_basic_auth(self):
  os.environ["KM_OIDC_CLIENT_SECRET"]="wrong-env-value"
  response=Mock(status_code=200);response.json.return_value={"id_token":"test-token"}
  with patch.object(m.requests,"post",return_value=response) as post:
   m.OIDCSettings.from_environment().exchange_code("code-fixture","verifier-fixture")
   args=post.call_args.kwargs
   self.assertEqual(args["auth"],("km-dev","unit-test-only-secret"))
   self.assertNotIn("client_secret",args["data"])
   self.assertTrue(args["verify"]);self.assertFalse(args["allow_redirects"])
 def test_missing_file_no_env_fallback(self):
  self.path.unlink();os.environ["KM_OIDC_CLIENT_SECRET"]="env-value"
  with self.assertRaises(m.OIDCError) as err:m.OIDCSettings.from_environment()._client_secret()
  self.assertNotIn(str(self.path),str(err.exception))
 def test_unsafe_permission_rejected(self):
  self.path.chmod(0o644)
  with self.assertRaises(m.OIDCError):m.OIDCSettings.from_environment()._client_secret()
 def test_newline_rejected(self):
  self.path.write_text("test-secret\n")
  with self.assertRaises(m.OIDCError):m.OIDCSettings.from_environment()._client_secret()
 def test_token_transport_failure_redacted(self):
  with patch.object(m.requests,"post",side_effect=m.requests.RequestException("private server details")):
   with self.assertRaises(m.OIDCError) as err:m.OIDCSettings.from_environment().exchange_code("fixture","fixture")
   self.assertEqual(str(err.exception),"OIDC token exchange failed")
 def test_ID_token_exact_issuer(self):
  from cryptography.hazmat.primitives.asymmetric import rsa
  key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  now=int(time.time());claims={"iss":BASE+"/","sub":"fixture-sub","aud":"km-dev","iat":now,"exp":now+300,"nonce":"nonce"}
  jwkclient=Mock();jwkclient.get_signing_key_from_jwt.return_value=Mock(key=key.public_key())
  with patch.object(m.jwt,"PyJWKClient",return_value=jwkclient):
   token=m.jwt.encode(claims,key,algorithm="RS256")
   self.assertEqual(m.OIDCSettings.from_environment().validate_id_token(token,"nonce")["iss"],BASE+"/")
   claims["iss"]=BASE;token=m.jwt.encode(claims,key,algorithm="RS256")
   with self.assertRaises(m.OIDCError):m.OIDCSettings.from_environment().validate_id_token(token,"nonce")
if __name__=="__main__":unittest.main(verbosity=1)
