import unittest
from projecthunt.core import Store, checked_url
DATA='name,website,email,location,source_url\nAcme,https://example.com,hello@example.com,US,https://directory.example/acme\nAcme,https://www.example.com,hello@example.com,US,https://directory.example/acme\nBad,https://other.example,bad-at-email,US,https://directory.example/bad\n'
class CoreTests(unittest.TestCase):
 def setUp(self): self.s=Store(':memory:'); self.res=self.s.import_csv(DATA); self.id=self.s.all()[0]['id']
 def test_import(self): self.assertEqual(self.res,{'imported':1,'duplicates':1,'invalid':1})
 def test_transition(self):
  with self.assertRaises(ValueError): self.s.transition(self.id,'Contacted')
 def test_unverified_contact(self):
  self.s.save_findings(self.id,[{'status':'confirmed','description':'Missing title','evidence':{'url':'https://example.com'}}]); self.s.scope(self.id)
  with self.assertRaisesRegex(ValueError,'verified contact'): self.s.draft(self.id)
 def test_unverified_evidence(self):
  self.s.save_findings(self.id,[{'status':'possible','description':'warning','evidence':{}}])
  with self.assertRaises(ValueError): self.s.scope(self.id)
 def test_private_ip(self):
  with self.assertRaises(ValueError): checked_url('http://127.0.0.1/')
 def test_report(self):
  self.assertEqual(self.s.report()['prospects_discovered'],1)
  self.assertEqual(self.s.report()['duplicates_rejected'],1)
  self.s.save_findings(self.id,[])
  self.assertEqual(self.s.report()['prospects_verified'],1)
if __name__=='__main__': unittest.main()
