"""Real API calls against synthetic, isolated, persistent test records."""
import os
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from projecthunt.api import app, service
from projecthunt.service import ProjectHunt, audit_html, validate_public_url, ProjectHuntError

CSV='name,website,email,location,source_url\nAcme,https://example.com,hello@example.com,US,https://directory.example/acme\nAcme,https://www.example.com,hello@example.com,US,https://directory.example/acme\nBad,https://invalid.example,bad-email,US,https://directory.example/bad\n'
class WorkflowTest(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(); self.url='sqlite:///'+self.temp.name+'/app.db';self.svc=ProjectHunt(self.url)
  app.dependency_overrides[service]=lambda:self.svc
  self.env=patch.dict(os.environ,{'PROJECTHUNT_API_KEY':'test-secret'});self.env.start()
  self.client=TestClient(app);self.headers={'Authorization':'Bearer test-secret'}
 def tearDown(self):
  self.client.close();app.dependency_overrides.clear();self.env.stop();self.svc.engine.dispose();self.temp.cleanup()
 def req(self,method,path,**kw): return self.client.request(method,path,headers=self.headers,**kw)
 def seed(self):
  r=self.req('POST','/prospects/import',files={'file':('test.csv',CSV,'text/csv')});self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(r.json(),{'imported':1,'duplicates':1,'invalid':1})
  return self.req('GET','/prospects').json()[0]['id']
 def test_import_audit_scope_draft_persist(self):
  self.assertEqual(self.client.get('/prospects').status_code,401)
  pid=self.seed()
  report=audit_html('https://example.com','<html><head><meta name="viewport" content="width=device-width"></head><body>Hi</body></html>')
  with patch('projecthunt.api.fetch_audit',return_value=report) as fetch:
   r=self.req('POST',f'/prospects/{pid}/audit')
  fetch.assert_called_once_with('https://example.com');self.assertEqual(r.status_code,200,r.text)
  self.assertEqual(len(self.req('GET',f'/prospects/{pid}/findings').json()),2)
  self.assertEqual(self.req('POST',f'/prospects/{pid}/draft').status_code,400)
  self.assertEqual(self.req('POST',f'/prospects/{pid}/scope',json={'capabilities':['metadata']}).status_code,200)
  self.assertEqual(self.req('POST',f'/prospects/{pid}/draft').status_code,400)
  self.assertEqual(self.req('POST',f'/prospects/{pid}/contact-review',json={'source_url':'https://directory.example/acme'}).status_code,200)
  drafted=self.req('POST',f'/prospects/{pid}/draft');self.assertEqual(drafted.status_code,200,drafted.text)
  self.assertIn('missing page title',drafted.json()['draft']);self.assertFalse(drafted.json()['sent'])
  self.assertEqual(self.req('POST',f'/prospects/{pid}/draft').status_code,400)
  metrics=self.req('GET','/performance').json();self.assertEqual((metrics['verified'],metrics['duplicates_rejected'],metrics['emails_sent']),(1,1,0))
  second=ProjectHunt(self.url);self.assertEqual(second.pipeline()[0]['stage'],'Draft Prepared');self.assertEqual(len(second.findings(pid)),2);second.engine.dispose()
 def test_possible_issue_cannot_drive_scope(self):
  pid=self.seed();self.svc.save_audit(pid,audit_html('https://example.com','<title>Okay</title><meta name="description" content="Fine"><img src="a.png">'))
  self.assertEqual(self.req('POST',f'/prospects/{pid}/scope',json={'capabilities':['accessibility']}).status_code,400)
 def test_suppression_and_validation(self):
  self.assertEqual(self.req('POST','/suppression',json={'email':'bad'}).status_code,400)
  self.req('POST','/suppression',json={'email':'hello@example.com'})
  pid=self.seed();self.svc.save_audit(pid,audit_html('https://example.com','<html></html>'))
  self.req('POST',f'/prospects/{pid}/scope',json={'capabilities':['metadata']})
  self.req('POST',f'/prospects/{pid}/contact-review',json={'source_url':'https://directory.example/acme'})
  self.assertEqual(self.req('POST',f'/prospects/{pid}/draft').status_code,400)
  with self.assertRaises(ProjectHuntError): validate_public_url('http://127.0.0.1/')
 def test_audit_reservation_and_durable_limit(self):
  from projecthunt.service import MAX_AUDITS_PER_HOUR
  rows='name,website,source_url\n'+''.join(f'Test{i},https://site{i}.example,https://directory.example/{i}\n' for i in range(MAX_AUDITS_PER_HOUR+1))
  self.assertEqual(self.svc.import_csv(rows)['imported'],MAX_AUDITS_PER_HOUR+1)
  ids=[p['id'] for p in self.svc.prospects()]
  for pid in ids[:MAX_AUDITS_PER_HOUR]:self.svc.reserve_audit(pid)
  with self.assertRaisesRegex(ProjectHuntError,'limit'):self.svc.reserve_audit(ids[-1])
  self.svc.fail_audit(ids[0],'timeout')
  self.assertEqual(self.svc.get(ids[0])['status'],'Discovered')
  with self.assertRaisesRegex(ProjectHuntError,'limit'):self.svc.reserve_audit(ids[0])
 def test_api_throttle(self):
  from projecthunt.api import _requests
  _requests.clear()
  try:
   for _ in range(120):self.assertEqual(self.req('GET','/performance').status_code,200)
   limited=self.req('GET','/performance')
   self.assertEqual(limited.status_code,429)
   self.assertEqual(limited.headers['Retry-After'],'60')
  finally:_requests.clear()
if __name__=='__main__': unittest.main()

class PostgresTest(unittest.TestCase):
 @unittest.skipUnless(os.environ.get('TEST_DATABASE_URL'), 'PostgreSQL service not configured')
 def test_postgres_persistence(self):
  from uuid import uuid4
  url=os.environ['TEST_DATABASE_URL'];first=ProjectHunt(url)
  domain=f'synthetic-{uuid4().hex}.example'
  result=first.import_csv(f'name,website,source_url\nSynthetic,https://{domain},https://directory.example/synthetic\n')
  self.assertEqual(result['imported'],1)
  second=ProjectHunt(url)
  self.assertTrue(any(p['domain']==domain for p in second.prospects()))
  first.engine.dispose();second.engine.dispose()
