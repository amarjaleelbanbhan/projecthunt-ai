"""The network target, response size and quota are security boundaries."""
import io
import unittest
from unittest.mock import patch
from projecthunt.service import ProjectHuntError, validate_public_url, fetch_audit, MAX_HTML

class FakeResponse:
 def __init__(self,status=200,body=b'<html></html>',content_type='text/html'):
  self.status=status;self.body=body;self.content_type=content_type
 def getheader(self,name,default=None):
  return self.content_type if name=='Content-Type' else default
 def read(self,n):return self.body[:n]

class FakeConnection:
 instances=[]
 def __init__(self,host,port,timeout,context=None):
  self.host=host;self.port=port;self.timeout=timeout;self.context=context;self.response=FakeResponse();self.connected=None;self.path=None
  self.instances.append(self)
 def request(self,method,path,headers):
  self.path=path;self.connected=self._create_connection((self.host,self.port),self.timeout)
 def getresponse(self):return self.response
 def close(self):pass

class SecurityTests(unittest.TestCase):
 def resolver(self,host,port,**kw):return [(2,1,6,'',('93.184.215.14',port))]
 def test_internal_and_ambiguous_dns_rejected(self):
  for url in ['http://127.0.0.1','http://localhost/','http://admin.local/','http://example.com:8080/','http://user:secret@example.com/','http://example.com\\@127.0.0.1/']:
   with self.subTest(url=url),self.assertRaises(ProjectHuntError):validate_public_url(url,self.resolver)
  mixed=lambda host,port,**kw:[(2,1,6,'',('93.184.215.14',port)),(2,1,6,'',('127.0.0.1',port))]
  with self.assertRaises(ProjectHuntError):validate_public_url('https://example.com',mixed)
 def test_validated_ip_is_actual_socket_target(self):
  FakeConnection.instances=[];target=[]
  def connect(address,timeout,source_address=None):target.append(address);return object()
  with patch('projecthunt.service.socket.getaddrinfo',side_effect=self.resolver),patch('projecthunt.service.socket.create_connection',side_effect=connect),patch('projecthunt.service.http.client.HTTPSConnection',FakeConnection):
   report=fetch_audit('https://example.com/path?x=1')
  conn=FakeConnection.instances[-1]
  self.assertEqual(target,[('93.184.215.14',443)])
  self.assertEqual((conn.host,conn.path,conn.timeout),('example.com','/path?x=1',5))
  self.assertIsNotNone(conn.context) # default validating SSL context and original SNI host
  self.assertEqual(report['url'],'https://example.com/path?x=1')
 def test_redirect_and_oversize_are_blocked(self):
  with patch('projecthunt.service.socket.getaddrinfo',side_effect=self.resolver),patch('projecthunt.service.socket.create_connection',return_value=object()),patch('projecthunt.service.http.client.HTTPConnection',FakeConnection):
   FakeConnection.instances=[]
   original=FakeConnection.getresponse
   try:
    FakeConnection.getresponse=lambda self:FakeResponse(302)
    with self.assertRaisesRegex(ProjectHuntError,'redirect'):fetch_audit('http://example.com')
    FakeConnection.getresponse=lambda self:FakeResponse(200,b'a'*(MAX_HTML+1))
    with self.assertRaisesRegex(ProjectHuntError,'1 MB'):fetch_audit('http://example.com')
   finally:FakeConnection.getresponse=original
if __name__=='__main__':unittest.main()
