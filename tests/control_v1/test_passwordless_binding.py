import unittest, tempfile, os, json, sqlite3, uuid, time, hashlib, base64, concurrent.futures
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse, parse_qs
from contextlib import contextmanager
from fastapi import FastAPI
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt
from src import km_control as kc
from src import control_auth_routes as routes
from src.oidc_control import OIDCSettings, OIDCError

ISSUER='https://identity.test/'
KEY=rsa.generate_private_key(public_exponent=65537,key_size=2048)
class BindingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.env=patch.dict(os.environ,{'KM_CONTROL_DB_URL':'sqlite:///'+self.tmp.name+'/control.db','KM_CONTROL_SESSION_SIGNING_KEY':'test-only-control-key-'+uuid.uuid4().hex,'KM_OIDC_BINDING_SIGNING_KEY':'test-only-binding-key-'+uuid.uuid4().hex,'KM_ENTRY_SESSION_SIGNING_KEY':'test-only-entry-key-'+uuid.uuid4().hex,'KM_ENABLED_INSTANCE_IDS':'test,da40,rd2','KM_TEST_PUBLIC_ORIGIN':'https://km.test','KM_DA40_PUBLIC_ORIGIN':'https://km.test/da40','KM_RD2_PUBLIC_ORIGIN':'https://km.test/rd2'})
  self.env.start();self.r=kc.ControlRegistry.from_environment()
  self.admin=self.user('admin',True);self.target=self.user('target');self.normal=self.user('normal')
  self.app=FastAPI();self.app.include_router(routes.router);self.app.include_router(routes.oidc_router)
  self.client=TestClient(self.app,base_url='https://km.test')
  self.settings=OIDCSettings(ISSUER,'https://identity.test/connect/authorize','https://identity.test/connect/token','https://identity.test/jwks','test-client','https://km.test/oidc/callback','https://km.test/oidc/logout/callback','client_secret_basic','','',('openid','profile','email'),('RS256',),{'name':'name','email':'email','account':'preferred_username','department':'department','team':'team'},'https://identity.test/connect/logout')
 def tearDown(self):self.client.close();self.env.stop();self.tmp.cleanup()
 def user(self,name,admin=False,status='active'):
  uid=str(uuid.uuid4());now=int(time.time())
  with self.r._connection() as c:c.execute('INSERT INTO km_users VALUES(?,?,?,?,?,?,?,?)',(uid,name,'not-a-login-password',status,admin,1,now,now))
  return self.r.get_user(uid)
 def identity(self,sub='subject-one',**profile):return self.r.upsert_external_identity(ISSUER,sub,{'name':'Fixture Name','email':'same@example.test','account':'same',**profile})
 def admin_cookie(self,user=None):self.client.cookies.set(routes.CONTROL_COOKIE,kc.issue_control_session(user or self.admin),domain="km.test",path="/")
 def callback(self,sub='subject-one',state=None,**claims_override):
  state,verifier,nonce=self.r.create_oidc_transaction() if state is None else state
  self.client.cookies.set(routes.TRANSACTION_COOKIE,hashlib.sha256(state.encode()).hexdigest(),domain="km.test",path="/oidc/")
  claims={'iss':ISSUER,'aud':'test-client','sub':sub,'iat':int(time.time()),'exp':int(time.time())+60,'nonce':nonce,'email':'same@example.test','preferred_username':'same','name':'Fixture Name','department':'Admin','team':'Leader',**claims_override}
  token=jwt.encode(claims,KEY,algorithm='RS256',headers={'kid':'fixture-key'})
  with patch.object(routes,'_oidc_settings',return_value=self.settings),patch.object(OIDCSettings,'exchange_code',return_value={'id_token':token}) as exchange,patch('jwt.PyJWKClient.get_signing_key_from_jwt',return_value=type('Key',(),{'key':KEY.public_key()})()):
   result=self.client.get('/oidc/callback',params={'code':'test-authorization-code','state':state},follow_redirects=False)
   if result.status_code==303:exchange.assert_called_once_with('test-authorization-code',verifier)
  return result
 def test_login_state_nonce_pkce_s256(self):
  with patch.object(routes,'_oidc_settings',return_value=self.settings):r=self.client.get('/oidc/login',follow_redirects=False)
  self.assertEqual(r.status_code,302);q=parse_qs(urlparse(r.headers['location']).query);self.assertEqual(q['code_challenge_method'],['S256']);self.assertEqual(q['redirect_uri'],['https://km.test/oidc/callback'])
  nonce,verifier=self.r.consume_oidc_transaction(q['state'][0]);self.assertEqual(q['nonce'],[nonce]);self.assertEqual(q['code_challenge'][0],base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('='))
 def test_valid_callback_creates_pending_without_password(self):
  r=self.callback();self.assertEqual(r.status_code,303);self.assertEqual(r.headers['location'],'/oidc/binding.html');rows=self.r.list_external_identities();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['binding_status'],'pending');self.assertIsNone(rows[0]['user_id']);self.assertIn(routes.BINDING_COOKIE,self.client.cookies)
 def test_pending_clears_existing_control_and_entry_sessions(self):
  self.admin_cookie();self.client.cookies.set('km_entry_session','old-entry',domain='km.test',path='/');self.client.cookies.set('km_instance_route','test',domain='km.test',path='/');r=self.callback()
  cookies=r.headers.get_list('set-cookie');self.assertTrue(any('km_entry_session=' in v and 'Max-Age=0' in v for v in cookies));self.assertTrue(any('km_control_session=' in v and 'Max-Age=0' in v for v in cookies));self.client.cookies.clear();identity=self.r.list_external_identities()[0];self.client.cookies.set(routes.BINDING_COOKIE,kc.issue_oidc_binding_session(identity['identity_id']))
  for path in ['/api/auth/me','/api/auth/admin/users','/api/auth/admin/oidc-bindings']:self.assertEqual(self.client.get(path).status_code,401)
  for zone in ['test','da40','rd2']:self.assertEqual(self.client.post('/api/auth/select-instance',json={'instance_id':zone}).status_code,401)
  for zone in ['test','da40','rd2']:
   with self.assertRaises(kc.ControlAuthenticationError):kc.verify_entry_session(self.client.cookies[routes.BINDING_COOKIE],zone)
 def test_duplicate_callback_replay_rejected_and_retry_idempotent(self):
  transaction=self.r.create_oidc_transaction();self.assertEqual(self.callback(state=transaction).status_code,303);self.assertEqual(self.callback(state=transaction).status_code,401);self.assertEqual(self.callback().status_code,303);self.assertEqual(len(self.r.list_external_identities()),1)
 def test_invalid_id_tokens_rejected(self):
  for values in [{'iss':'https://wrong.test/'},{'aud':'wrong-client'},{'exp':int(time.time())-10},{'nonce':'wrong-nonce'}]:self.assertEqual(self.callback(**values).status_code,401)
  self.assertEqual(self.r.list_external_identities(),[])
 def test_signature_tampering_rejected(self):
  other=rsa.generate_private_key(public_exponent=65537,key_size=2048);token=jwt.encode({'iss':ISSUER,'aud':'test-client','sub':'x','iat':int(time.time()),'exp':int(time.time())+60,'nonce':'n'},other,algorithm='RS256')
  with patch('jwt.PyJWKClient.get_signing_key_from_jwt',return_value=type('Key',(),{'key':KEY.public_key()})()):
   with self.assertRaises(OIDCError):self.settings.validate_id_token(token,'n')
 def test_email_and_username_do_not_autobind(self):
  first=self.identity('one');self.r.approve_external_identity(self.admin.user_id,first['identity_id'],self.target.user_id);second=self.identity('two');self.assertEqual(second['binding_status'],'pending');self.assertIsNone(second['user_id']);self.assertNotEqual(first['identity_id'],second['identity_id'])
 def test_exact_issuer_subject_key(self):
  first=self.identity();second=self.r.upsert_external_identity('https://other.test/','subject-one',{'email':'same@example.test'});self.assertNotEqual(first['identity_id'],second['identity_id'])
 def test_admin_selects_target_and_approval_does_not_modify_grants(self):
  self.r.grant(self.admin.user_id,self.target.user_id,'rd2','user');before=self.r.grants_for(self.target.user_id);identity=self.identity();self.admin_cookie();r=self.client.post('/api/auth/admin/oidc-bindings/'+identity['identity_id']+'/approve',json={'target_km_account_id':self.target.user_id});self.assertEqual(r.status_code,200);self.assertEqual(r.json()['status'],'approved');self.assertEqual(self.r.get_external_identity(identity['identity_id'])['user_id'],self.target.user_id);self.assertEqual(self.r.grants_for(self.target.user_id),before);self.assertEqual(len(self.r.list_users()),3)
 def test_admin_approval_requires_existing_active_target(self):
  i=self.identity();self.admin_cookie();url='/api/auth/admin/oidc-bindings/'+i['identity_id']+'/approve';self.assertEqual(self.client.post(url,json={}).status_code,422);self.assertEqual(self.client.post(url,json={'target_km_account_id':'missing'}).status_code,422);disabled=self.user('disabled',status='disabled');self.assertEqual(self.client.post(url,json={'target_km_account_id':disabled.user_id}).status_code,422)
 def test_admin_only_review(self):
  i=self.identity();url='/api/auth/admin/oidc-bindings/'+i['identity_id']+'/approve';self.assertEqual(self.client.post(url,json={'target_km_account_id':self.target.user_id}).status_code,401);self.admin_cookie(self.normal);self.assertEqual(self.client.get('/api/auth/admin/oidc-bindings').status_code,403);self.assertEqual(self.client.post(url,json={'target_km_account_id':self.target.user_id}).status_code,403)
 def test_stale_or_disabled_admin_denied(self):
  self.admin_cookie();self.r.set_user_status(self.admin.user_id,self.admin.user_id,'disabled');self.assertEqual(self.client.get('/api/auth/admin/oidc-bindings').status_code,401)
 def test_reject_requires_reason_and_never_binds(self):
  i=self.identity();self.admin_cookie();url='/api/auth/admin/oidc-bindings/'+i['identity_id']+'/reject';self.assertEqual(self.client.post(url,json={'reason':'   '}).status_code,422);self.assertEqual(self.client.post(url,json={'reason':'No matching approved KM account'}).status_code,200);row=self.r.get_external_identity(i['identity_id']);self.assertEqual(row['binding_status'],'rejected');self.assertIsNone(row['user_id']);self.assertEqual(row['reviewed_by'],self.admin.user_id);self.assertTrue(row['reviewed_at']);self.assertEqual(self.callback().headers['location'],'/oidc/binding.html');self.assertEqual(self.r.get_external_identity(i['identity_id'])['binding_status'],'rejected')
 def test_db_unique_issuer_subject_and_one_to_one(self):
  first=self.identity();second=self.identity('two');self.r.approve_external_identity(self.admin.user_id,first['identity_id'],self.target.user_id)
  with self.assertRaises(kc.ControlError):self.r.approve_external_identity(self.admin.user_id,second['identity_id'],self.target.user_id)
  with self.assertRaises(sqlite3.IntegrityError):
   with self.r._connection() as c:c.execute("INSERT INTO km_external_identities SELECT ?,provider_issuer,subject,user_id,binding_status,profile_json,requested_at,verified_at,approved_at,approved_by,reviewed_by,reviewed_at,reject_reason,updated_at FROM km_external_identities WHERE identity_id=?",(str(uuid.uuid4()),first['identity_id']))
  with self.assertRaises(sqlite3.IntegrityError):
   with self.r._connection() as c:c.execute("UPDATE km_external_identities SET binding_status='bound',user_id=? WHERE identity_id=?",(self.target.user_id,second['identity_id']))
 def test_approved_next_login_session_and_independent_grants(self):
  self.r.grant(self.admin.user_id,self.target.user_id,'test','user');i=self.identity();self.r.approve_external_identity(self.admin.user_id,i['identity_id'],self.target.user_id);r=self.callback();self.assertEqual(r.status_code,303);self.assertEqual(r.headers['location'],'/login.html');self.assertIn(routes.CONTROL_COOKIE,self.client.cookies);self.assertEqual(self.client.get('/api/auth/me').json()['instances'],[{'instance_id':'test','role':'user'}]);self.assertFalse(self.client.get('/api/auth/me').json()['is_admin']);self.assertEqual(self.client.post('/api/auth/select-instance',json={'instance_id':'rd2'}).status_code,403);self.assertEqual(self.client.post('/api/auth/select-instance',json={'instance_id':'test'}).status_code,200)
 def test_approved_disabled_account_cannot_obtain_business_session(self):
  i=self.identity();self.r.approve_external_identity(self.admin.user_id,i['identity_id'],self.target.user_id);self.r.set_user_status(self.admin.user_id,self.target.user_id,'disabled');self.callback();self.assertEqual(self.client.get('/api/auth/me').status_code,401)
 def test_old_password_binding_route_removed(self):
  i=self.identity();self.client.cookies.set(routes.BINDING_COOKIE,kc.issue_oidc_binding_session(i['identity_id']));self.assertEqual(self.client.post('/api/auth/oidc/binding/verify',json={'username':'target','password':'unused-test-value'}).status_code,404);self.assertFalse(hasattr(self.r,'verify_external_identity_local_account'))
 def test_status_profile_no_sub_secret_or_tokens(self):
  i=self.identity();self.client.cookies.set(routes.BINDING_COOKIE,kc.issue_oidc_binding_session(i['identity_id']));r=self.client.get('/api/auth/oidc/binding');self.assertEqual(r.status_code,200);self.assertEqual(r.headers['cache-control'],'no-store');self.assertNotIn('subject',r.text);self.assertNotIn('subject-one',r.text);self.assertNotIn('password',r.text);self.assertNotIn('token',r.text);self.assertEqual(r.json()['profile']['name'],'Fixture Name')
 def test_existing_grant_selection_logout_regression(self):
  self.r.grant(self.admin.user_id,self.normal.user_id,'da40','user');self.admin_cookie(self.r.get_user(self.normal.user_id));self.assertEqual(self.client.get('/api/auth/me').status_code,200);self.assertEqual(self.client.post('/api/auth/select-instance',json={'instance_id':'da40'}).status_code,200);r=self.client.post('/api/auth/logout');self.assertEqual(r.status_code,200);self.assertEqual(self.client.get('/api/auth/me').status_code,401);self.assertEqual(self.client.get('/oidc/logout/callback',follow_redirects=False).headers['location'],'/signed-out')
 def test_callback_requires_same_browser_transaction(self):
  state,verifier,nonce=self.r.create_oidc_transaction()
  with patch.object(routes,'_oidc_settings',return_value=self.settings),patch.object(OIDCSettings,'exchange_code') as exchange:
   r=self.client.get('/oidc/callback',params={'code':'fixture','state':state},follow_redirects=False);self.assertEqual(r.status_code,401);exchange.assert_not_called()
  self.assertEqual(self.r.consume_oidc_transaction(state),(nonce,verifier))
 def test_transaction_cookie_secure_lax_and_http_only(self):
  with patch.object(routes,'_oidc_settings',return_value=self.settings):r=self.client.get('/oidc/login',follow_redirects=False)
  cookie=r.headers['set-cookie'];self.assertIn('HttpOnly',cookie);self.assertIn('Secure',cookie);self.assertIn('SameSite=lax',cookie);self.assertIn('Path=/oidc/',cookie)
 def test_profile_cannot_set_role_or_target_account(self):
  i=self.identity(role='admin',target_km_account_id=self.admin.user_id);self.assertNotIn('role',json.loads(i['profile_json']));self.assertIsNone(i['user_id']);self.assertEqual(i['binding_status'],'pending')
 def test_review_payload_cannot_override_identity_or_grants(self):
  i=self.identity();self.admin_cookie();r=self.client.post('/api/auth/admin/oidc-bindings/'+i['identity_id']+'/approve',json={'target_km_account_id':self.target.user_id,'role':'admin'});self.assertEqual(r.status_code,422)

if __name__=='__main__':unittest.main(verbosity=2)
