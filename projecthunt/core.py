"""Deterministic prospect pipeline; SQLite local store, one owner per database."""
import csv
import io
import ipaddress
import json
import re
import socket
import sqlite3
import time
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser

STAGES = ('Discovered','Verified','Qualified','Draft Prepared','Contacted','Replied','Meeting','Proposal','Accepted','Rejected','Delivered')
NEXT = {'Discovered':{'Verified'},'Verified':{'Qualified'},'Qualified':{'Draft Prepared'},'Draft Prepared':{'Contacted'},'Contacted':{'Replied'},'Replied':{'Meeting','Proposal','Rejected'},'Meeting':{'Proposal','Rejected'},'Proposal':{'Accepted','Rejected'},'Accepted':{'Delivered'},'Rejected':set(),'Delivered':set()}
EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

class AuditParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.title=False; self.description=False; self.images=[]; self.links=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag=='title': self.title=True
        if tag=='meta' and a.get('name','').lower()=='description' and a.get('content'): self.description=True
        if tag=='img': self.images.append(a)
        if tag=='a' and a.get('href'): self.links.append(a['href'])

class Store:
    def __init__(self, path='projecthunt.db'):
        self.db=sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE IF NOT EXISTS prospects(id TEXT PRIMARY KEY, name TEXT NOT NULL, website TEXT NOT NULL, domain TEXT NOT NULL UNIQUE, email TEXT, email_verified INTEGER NOT NULL DEFAULT 0, location TEXT, industry TEXT, source_url TEXT NOT NULL, discovered_at INTEGER NOT NULL, stage TEXT NOT NULL, findings TEXT NOT NULL DEFAULT '[]', scope TEXT, draft TEXT, approved INTEGER NOT NULL DEFAULT 0, sent_at INTEGER, payment_cents INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, prospect_id TEXT, kind TEXT NOT NULL, at INTEGER NOT NULL, detail TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS suppression(email TEXT PRIMARY KEY);''')
    def event(self,pid,kind,detail=''):
        self.db.execute('INSERT INTO events(prospect_id,kind,at,detail) VALUES(?,?,?,?)',(pid,kind,int(time.time()),detail)); self.db.commit()
    def get(self,pid):
        row=self.db.execute('SELECT * FROM prospects WHERE id=?',(pid,)).fetchone()
        if not row: raise ValueError('prospect not found')
        return dict(row)
    def all(self): return [dict(x) for x in self.db.execute('SELECT * FROM prospects ORDER BY discovered_at DESC')]
    def import_csv(self, content):
        result={'imported':0,'duplicates':0,'invalid':0}
        for r in csv.DictReader(io.StringIO(content)):
            try:
                u=urllib.parse.urlsplit(r['website']); domain=(u.hostname or '').lower().removeprefix('www.')
                if u.scheme not in ('http','https') or not domain or not r.get('name') or not r.get('source_url'): raise ValueError()
                email=r.get('email','').strip().lower() or None
                if email and not EMAIL.fullmatch(email): raise ValueError()
                if self.db.execute('SELECT 1 FROM prospects WHERE domain=? OR (name=? AND location=?)',(domain,r['name'].strip(),r.get('location',''))).fetchone(): result['duplicates']+=1; self.event(None,'duplicate',domain); continue
                pid=str(uuid.uuid4())
                self.db.execute('INSERT INTO prospects(id,name,website,domain,email,location,industry,source_url,discovered_at,stage) VALUES(?,?,?,?,?,?,?,?,?,?)',(pid,r['name'].strip(),r['website'],domain,email,r.get('location',''),r.get('industry',''),r['source_url'],int(time.time()),'Discovered'))
                self.db.commit(); self.event(pid,'discovered',r['source_url']); result['imported']+=1
            except (ValueError,KeyError,sqlite3.IntegrityError): result['invalid']+=1
        return result
    def transition(self,pid,stage):
        old=self.get(pid)['stage']
        if stage not in NEXT[old]: raise ValueError('invalid stage transition')
        self.db.execute('UPDATE prospects SET stage=? WHERE id=?',(stage,pid)); self.db.commit(); self.event(pid,'stage',old+' -> '+stage)
    def save_findings(self,pid,findings):
        self.db.execute('UPDATE prospects SET findings=? WHERE id=?',(json.dumps(findings),pid)); self.db.commit(); self.transition(pid,'Verified')
    def scope(self,pid):
        p=self.get(pid); confirmed=[x for x in json.loads(p['findings']) if x['status']=='confirmed']
        if not confirmed: raise ValueError('no confirmed findings')
        if p['stage']=='Verified': self.transition(pid,'Qualified')
        finding=confirmed[0]
        scope={'problem':finding['description'],'evidence':finding['evidence'],'solution':'Review and correct '+finding['description'].lower(),'deliverables':['Reproduction notes','Targeted fix','Before/after verification'],'assumptions':['Site owner grants access'],'risks':['Underlying platform may limit remediation'],'estimate':'Requires discovery; no price established'}
        self.db.execute('UPDATE prospects SET scope=? WHERE id=?',(json.dumps(scope),pid)); self.db.commit(); return scope
    def draft(self,pid):
        p=self.get(pid)
        if p['stage']!='Qualified' or not p['scope']: raise ValueError('scope required')
        if not p['email'] or not p['email_verified']: raise ValueError('verified contact required')
        if self.db.execute('SELECT 1 FROM suppression WHERE email=?',(p['email'],)).fetchone() or p['sent_at']: raise ValueError('contact suppressed or already contacted')
        s=json.loads(p['scope']); body=f"Subject: Quick note about {p['name']} website\nTo: {p['email']}\n\nHello,\n\nI noticed {s['problem'].lower()} at {s['evidence']['url']}. I can review and fix this with a short before/after check. Would it be useful to discuss?\n\nAmar Jaleel\nAmar Digital Systems\nhttps://amarjaleel.me"
        self.db.execute('UPDATE prospects SET draft=?,approved=0 WHERE id=?',(body,pid)); self.db.commit(); self.transition(pid,'Draft Prepared'); self.event(pid,'draft_prepared'); return body
    def report(self):
        counts={row['kind']:row['n'] for row in self.db.execute('SELECT kind,count(*) n FROM events GROUP BY kind')}
        verified=self.db.execute("SELECT count(*) FROM events WHERE kind='stage' AND detail='Discovered -> Verified'").fetchone()[0]
        stages={row['stage']:row['n'] for row in self.db.execute('SELECT stage,count(*) n FROM prospects GROUP BY stage')}
        return {'prospects_discovered':counts.get('discovered',0),'prospects_verified':verified,'duplicates_rejected':counts.get('duplicate',0),'emails_prepared':counts.get('draft_prepared',0),'emails_sent':counts.get('sent',0),'replies_received':counts.get('reply',0),'accepted':counts.get('accepted',0),'confirmed_revenue_cents':self.db.execute('SELECT coalesce(sum(payment_cents),0) FROM prospects').fetchone()[0],'current_stages':stages,'conversion':'insufficient data' if not counts.get('sent') else {'numerator':counts.get('reply',0),'denominator':counts['sent']}}

def checked_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443): raise ValueError('unsafe URL')
    for item in socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM):
        addr=ipaddress.ip_address(item[4][0]);
        if not addr.is_global: raise ValueError('nonpublic address')
    return p

def audit(url):
    checked_url(url)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl): raise ValueError('redirect blocked; inspect separately')
    opener=urllib.request.build_opener(NoRedirect)
    req=urllib.request.Request(url,headers={'User-Agent':'ProjectHuntAI/0.1 (+https://amarjaleel.me)'})
    try:
        with opener.open(req,timeout=8) as response:
            ctype=response.headers.get('Content-Type','')
            if 'text/html' not in ctype: raise ValueError('not HTML')
            body=response.read(1_000_001)
            if len(body)>1_000_000: raise ValueError('page too large')
            parser=AuditParser(); parser.feed(body.decode('utf-8','replace'))
            findings=[]
            for name,present in [('title element',parser.title),('meta description',parser.description)]:
                if not present: findings.append({'status':'confirmed','description':'Missing '+name,'evidence':{'url':url,'method':'HTML inspection','timestamp':int(time.time())}})
            for img in parser.images:
                if not img.get('alt'): findings.append({'status':'possible','description':'Image missing alt attribute','evidence':{'url':url,'method':'HTML inspection','timestamp':int(time.time())}})
            return {'url':url,'status_code':response.status,'findings':findings,'limitations':['No rendered mobile, performance, form, or linked-resource audit'],'audited_at':int(time.time())}
    except (OSError,UnicodeError) as e: return {'url':url,'error':type(e).__name__,'findings':[],'audited_at':int(time.time())}
