import asyncio
import os
import time
import unittest
from unittest.mock import patch
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from projecthunt.remote_mcp import JWTVerifier, create_app
from projecthunt.api import app as api_app, service as api_service
from projecthunt.service import ProjectHunt, audit_html
import tempfile
import json

ISSUER='https://login.example.com';RESOURCE='https://projecthunt.example.com/mcp'
class RemoteSecurityTest(unittest.TestCase):
 def setUp(self):
  self.private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
  pub=jwt.algorithms.RSAAlgorithm.to_jwk(self.private.public_key(),as_dict=True)
  pub['kid']='test-key';pub['alg']='RS256';pub['use']='sig'
  self.jwks={'keys':[pub]}
  self.verifier=JWTVerifier(ISSUER,ISSUER+'/jwks',RESOURCE,'owner-123')
  self.patcher=patch.object(self.verifier.keys,'fetch_data',return_value=self.jwks);self.patcher.start()
 def tearDown(self):self.patcher.stop()
 def token(self,**changes):
  claims={'iss':ISSUER,'aud':RESOURCE,'sub':'owner-123','scope':'projecthunt:access',
          'iat':int(time.time()),'exp':int(time.time())+60,'client_id':'chatgpt'}
  claims.update(changes)
  return jwt.encode(claims,self.private,algorithm='RS256',headers={'kid':'test-key'})
 def test_valid_token_and_rejections(self):
  self.assertIsNotNone(asyncio.run(self.verifier.verify_token(self.token())))
  for claims in [{'sub':'other'},{'aud':'https://other.example.com/mcp'},
                 {'scope':'profile'},{'scope':['projecthunt:access']},{'exp':int(time.time())-100}]:
   with self.subTest(claims=claims):self.assertIsNone(asyncio.run(self.verifier.verify_token(self.token(**claims))))
 def test_configuration_fails_closed(self):
  with self.assertRaises(ValueError):JWTVerifier('http://login.example.com',ISSUER+'/jwks',RESOURCE,'owner')
  with self.assertRaises(ValueError):JWTVerifier(ISSUER,'https://different.example.com/jwks',RESOURCE,'owner')
  with patch.dict(os.environ,{'OAUTH_ISSUER':ISSUER,'JWT_JWKS_URL':ISSUER+'/jwks',
                              'MCP_PUBLIC_URL':RESOURCE,'PROJECTHUNT_OWNER_SUB':'owner-123'}):
   app=create_app()
   with TestClient(app,base_url='https://projecthunt.example.com') as c:
    r=c.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}},headers={'Accept':'application/json, text/event-stream'})
    self.assertEqual(r.status_code,401)
    metadata=c.get('/.well-known/oauth-protected-resource/mcp')
    self.assertEqual(metadata.status_code,200,metadata.text)
    self.assertEqual(metadata.json()['resource'],RESOURCE)
 def test_authenticated_mcp_to_api_persists_full_workflow(self):
  temp=tempfile.TemporaryDirectory()
  db=ProjectHunt('sqlite:///'+temp.name+'/integration.db')
  api_app.dependency_overrides[api_service]=lambda:db
  def api_request(method,path,*,data=None,files=None):
   with TestClient(api_app) as api:
    response=api.request(method,path,headers={'Authorization':'Bearer integration-key'},json=data,files=files)
    response.raise_for_status()
    return response.json()
  env={'OAUTH_ISSUER':ISSUER,'JWT_JWKS_URL':ISSUER+'/jwks','MCP_PUBLIC_URL':RESOURCE,
       'PROJECTHUNT_OWNER_SUB':'owner-123','PROJECTHUNT_API_KEY':'integration-key'}
  report=audit_html('https://example.com','<html><head></head><body>Test</body></html>')
  try:
   with patch.dict(os.environ,env),patch('jwt.PyJWKClient.fetch_data',return_value=self.jwks),patch('projecthunt.mcp_server.request',side_effect=api_request),patch('projecthunt.api.fetch_audit',return_value=report):
    with TestClient(create_app(),base_url='https://projecthunt.example.com') as remote:
     headers={'Authorization':'Bearer '+self.token(),'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-06-18'}
     def call(name,args):
      r=remote.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}},headers=headers)
      self.assertEqual(r.status_code,200,r.text)
      data=r.json()['result'];self.assertFalse(data.get('isError'),data)
      return data.get('structuredContent') or json.loads(data['content'][0]['text'])
     self.assertEqual(remote.post('/mcp',json={'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}},headers=headers).status_code,200)
     imported=call('import_prospects',{'csv_text':'name,website,email,source_url\nSynthetic,https://example.com,hello@example.com,https://directory.example/synthetic\n'})
     self.assertEqual(imported['imported'],1)
     rows=call('search_prospects',{})
     if isinstance(rows,dict):rows=rows['result']
     pid=rows[0]['id']
     call('audit_website',{'prospect_id':pid})
     scope=call('prepare_proposal',{'prospect_id':pid,'capabilities':['metadata']})
     self.assertEqual(scope['problem'],'Missing page title')
     call('review_contact',{'prospect_id':pid,'source_url':'https://directory.example/synthetic'})
     draft=call('create_email_draft',{'prospect_id':pid})
     self.assertFalse(draft['sent'])
     self.assertEqual(call('get_performance_report',{})['verified'],1)
     self.assertEqual(db.pipeline()[0]['stage'],'Draft Prepared')
  finally:
   api_app.dependency_overrides.clear();db.engine.dispose();temp.cleanup()
if __name__=='__main__':unittest.main()
