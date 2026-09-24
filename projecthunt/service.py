"""ProjectHunt v0.2: sourced prospects, reproducible audits, and review-only outreach."""
from __future__ import annotations
import csv
import http.client
import io
import ipaddress
import json
import re
import socket
import ssl
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlsplit
from uuid import uuid4

from bs4 import BeautifulSoup
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, create_engine, func, select, update, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

EMAIL = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")
USER_AGENT = "ProjectHuntAI/0.2 (+https://amarjaleel.me)"
MAX_HTML = 1_000_000
MAX_AUDITS_PER_HOUR = 20

class Base(DeclarativeBase): pass

class Prospect(Base):
    __tablename__ = 'prospects'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(300))
    website: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(253), unique=True, index=True)
    location: Mapped[str] = mapped_column(String(300), default='')
    industry: Mapped[str] = mapped_column(String(200), default='')
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    contact_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source_url: Mapped[str] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status: Mapped[str] = mapped_column(String(40), default='Discovered')
    findings: Mapped[list[Finding]] = relationship(back_populates='prospect', cascade='all, delete-orphan')

class Finding(Base):
    __tablename__='findings'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    prospect_id: Mapped[str] = mapped_column(ForeignKey('prospects.id'), index=True)
    status: Mapped[str] = mapped_column(String(30))
    code: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    prospect: Mapped[Prospect] = relationship(back_populates='findings')

class Opportunity(Base):
    __tablename__='opportunities'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    prospect_id: Mapped[str] = mapped_column(ForeignKey('prospects.id'), unique=True, index=True)
    scope: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(320), nullable=True)
    stage: Mapped[str] = mapped_column(String(40), default='Discovered')
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

class Suppression(Base):
    __tablename__='suppressions'
    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    reason: Mapped[str] = mapped_column(String(100), default='opt_out')

class Event(Base):
    __tablename__='events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prospect_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(80))
    detail: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class ProjectHuntError(ValueError): pass

def validate_public_url(url: str, resolver=None) -> tuple[str,int,str,str]:
    """Resolve once; return a validated address for the *actual* socket connection."""
    if not isinstance(url,str) or len(url)>2048 or any(ch in url for ch in ('\\','\r','\n','\t')):
        raise ProjectHuntError('invalid audit URL')
    try:
        parts=urlsplit(url)
        port=parts.port or (443 if parts.scheme=='https' else 80)
        host=parts.hostname
        if (parts.scheme not in ('http','https') or not host or parts.username or parts.password
                or parts.port not in (None,80,443) or parts.fragment or host.endswith('.')):
            raise ProjectHuntError('URL must be public HTTP(S) with no credentials, fragment or custom port')
        host=host.encode('idna').decode('ascii').lower()
        try:
            literal=ipaddress.ip_address(host)
        except ValueError:
            literal=None
        if literal and not literal.is_global: raise ProjectHuntError('non-public network address')
        if host in ('localhost','localhost.localdomain') or host.endswith(('.local','.internal','.localhost')):
            raise ProjectHuntError('internal hostname')
        resolver=resolver or socket.getaddrinfo
        addresses=resolver(host,port,type=socket.SOCK_STREAM)
        ips={entry[4][0] for entry in addresses}
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise ProjectHuntError('non-public network address')
        return host,port,sorted(ips)[0],parts.path or '/'
    except (socket.gaierror,UnicodeError,ValueError) as exc:
        raise ProjectHuntError('audit URL does not resolve exclusively to public addresses') from exc

def domain_of(url: str) -> str:
    parts=urlsplit(url)
    if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:
        raise ProjectHuntError('invalid website URL')
    return parts.hostname.lower().removeprefix('www.')

def finding(code, description, url, status='confirmed', detail=None):
    return {'status':status,'code':code,'description':description,'evidence':{'url':url,'method':'Beautiful Soup static HTML inspection','tool':'beautifulsoup4','detail':detail,'observed_at':datetime.now(timezone.utc).isoformat()}}

def audit_html(url: str, html: str, status_code: int=200):
    soup=BeautifulSoup(html,'html.parser')
    result=[]
    if not soup.title or not soup.title.get_text(strip=True): result.append(finding('missing_title','Missing page title',url))
    if not soup.find('meta',attrs={'name':re.compile('^description$',re.I),'content':True}): result.append(finding('missing_description','Missing meta description',url))
    if not soup.find('meta',attrs={'name':re.compile('^viewport$',re.I)}): result.append(finding('missing_viewport','Missing viewport metadata',url,'possible'))
    for image in soup.find_all('img',limit=20):
        if 'alt' not in image.attrs: result.append(finding('missing_alt','Image has no alt attribute',urljoin(url,image.get('src','')),'possible'))
    return {'url':url,'status_code':status_code,'findings':result,'limitations':['Static HTML only; no rendered layout, broken-link crawl, performance or form submission'],'audited_at':datetime.now(timezone.utc).isoformat()}

def fetch_audit(url: str):
    host,port,pinned_ip,_=validate_public_url(url)
    parts=urlsplit(url)
    conn=(http.client.HTTPSConnection(host,port,timeout=5,context=ssl.create_default_context())
          if parts.scheme=='https' else http.client.HTTPConnection(host,port,timeout=5))
    # http.client uses `host` for Host, SNI and certificate validation, while the
    # socket connects to the previously validated address. No proxy or DNS relookup.
    conn._create_connection=lambda address,timeout,source_address=None: socket.create_connection(
        (pinned_ip,port),timeout,source_address)
    try:
        conn.request('GET',(parts.path or '/')+('?' + parts.query if parts.query else ''),
                     headers={'User-Agent':USER_AGENT,'Accept-Encoding':'identity'})
        response=conn.getresponse()
        if 300<=response.status<400: raise ProjectHuntError('redirect blocked; audit target separately')
        if response.status>=400: raise ProjectHuntError(f'HTTP {response.status}')
        if 'text/html' not in response.getheader('Content-Type','').lower(): raise ProjectHuntError('not an HTML response')
        declared=response.getheader('Content-Length')
        if declared and declared.isdigit() and int(declared)>MAX_HTML: raise ProjectHuntError('HTML exceeds 1 MB')
        body=response.read(MAX_HTML+1)
        if len(body)>MAX_HTML: raise ProjectHuntError('HTML exceeds 1 MB')
        return audit_html(url,body.decode('utf-8','replace'),response.status)
    except (OSError,http.client.HTTPException,ssl.SSLError) as exc:
        raise ProjectHuntError(f'website request failed: {type(exc).__name__}') from exc
    finally:
        conn.close()

class ProjectHunt:
    def __init__(self, database_url: str):
        self.engine=create_engine(database_url,pool_pre_ping=True)
        Base.metadata.create_all(self.engine) # initial development schema; migrations required before production
        self.sessions=sessionmaker(self.engine, expire_on_commit=False)
    def import_csv(self, content: str):
        stats={'imported':0,'duplicates':0,'invalid':0}
        rows=csv.DictReader(io.StringIO(content.lstrip('\ufeff')))
        if not rows.fieldnames or not {'name','website','source_url'}.issubset(rows.fieldnames): raise ProjectHuntError('CSV requires name,website,source_url headers')
        for row in rows:
            try:
                name=(row.get('name') or '').strip(); url=(row.get('website') or '').strip(); source=(row.get('source_url') or '').strip()
                if not name or len(name)>300 or len(url)>2048 or len(source)>2048 or not source or urlsplit(source).scheme not in ('http','https'): raise ProjectHuntError('invalid name, website or source')
                dom=domain_of(url); email=(row.get('email') or '').strip().lower() or None
                if email and (len(email)>320 or not EMAIL.fullmatch(email)): raise ProjectHuntError('invalid contact')
                if len(row.get('location') or '')>300 or len(row.get('industry') or '')>200: raise ProjectHuntError('invalid location or industry')
                with self.sessions.begin() as db:
                    if db.scalar(select(Prospect.id).where((Prospect.domain==dom)|((func.lower(Prospect.name)==name.lower())&(Prospect.location==(row.get('location') or ''))))):
                        db.add(Event(kind='duplicate',detail=dom)); stats['duplicates']+=1; continue
                    p=Prospect(name=name,website=url,domain=dom,location=row.get('location') or '',industry=row.get('industry') or '',email=email,source_url=source)
                    db.add(p); db.flush(); db.add(Opportunity(prospect_id=p.id)); db.add(Event(prospect_id=p.id,kind='discovered',detail=source)); stats['imported']+=1
            except (ProjectHuntError,TypeError): stats['invalid']+=1
        return stats
    def prospects(self):
        with self.sessions() as db: return [self._prospect(p) for p in db.scalars(select(Prospect).order_by(Prospect.discovered_at.desc())).all()]
    def _prospect(self,p):
        return {'id':p.id,'name':p.name,'website':p.website,'domain':p.domain,'email':p.email,'contact_verified':p.contact_verified,'source_url':p.source_url,'location':p.location,'industry':p.industry,'status':p.status}
    def get(self,pid):
        with self.sessions() as db:
            p=db.get(Prospect,pid)
            if not p: raise ProjectHuntError('prospect not found')
            return self._prospect(p)
    def save_audit(self,pid,report):
        with self.sessions.begin() as db:
            p=db.get(Prospect,pid)
            if not p: raise ProjectHuntError('prospect not found')
            if p.status not in ('Discovered','Auditing'): raise ProjectHuntError('audit already recorded')
            if report['url']!=p.website: raise ProjectHuntError('audit URL mismatch')
            for item in report['findings']:
                db.add(Finding(prospect_id=pid,status=item['status'],code=item['code'],description=item['description'],evidence=item['evidence']))
            p.status='Verified'
            opp=db.scalar(select(Opportunity).where(Opportunity.prospect_id==pid)); opp.stage='Verified'
            db.add(Event(prospect_id=pid,kind='verified',detail=report['url']))
        return report
    def reserve_audit(self,pid):
        """One audit per prospect and 20 per hour per single operator."""
        with self.sessions.begin() as db:
            if self.engine.dialect.name=='postgresql':
                db.execute(text('SELECT pg_advisory_xact_lock(8824003)'))
            cutoff=datetime.now(timezone.utc)-timedelta(hours=1)
            count=db.scalar(select(func.count()).select_from(Event).where(Event.kind=='audit_started',Event.created_at>=cutoff))
            if count>=MAX_AUDITS_PER_HOUR: raise ProjectHuntError('audit limit reached; retry after one hour')
            changed=db.execute(update(Prospect).where(Prospect.id==pid,Prospect.status=='Discovered').values(status='Auditing'))
            if changed.rowcount!=1: raise ProjectHuntError('prospect unavailable or audit already started')
            db.add(Event(prospect_id=pid,kind='audit_started',detail='one public HTML request'))
    def fail_audit(self,pid,error):
        with self.sessions.begin() as db:
            db.execute(update(Prospect).where(Prospect.id==pid,Prospect.status=='Auditing').values(status='Discovered'))
            db.add(Event(prospect_id=pid,kind='audit_failed',detail=str(error)[:100]))
    def findings(self,pid):
        with self.sessions() as db:
            return [{'id':f.id,'status':f.status,'code':f.code,'description':f.description,'evidence':f.evidence} for f in db.scalars(select(Finding).where(Finding.prospect_id==pid)).all()]
    def scope(self,pid, capabilities: list[str]):
        allowed={'metadata','accessibility'}
        if not set(capabilities).intersection(allowed): raise ProjectHuntError('capability profile must establish metadata or accessibility work')
        with self.sessions.begin() as db:
            p=db.get(Prospect,pid)
            if not p: raise ProjectHuntError('prospect not found')
            opp=db.scalar(select(Opportunity).where(Opportunity.prospect_id==pid))
            matches=[f for f in db.scalars(select(Finding).where(Finding.prospect_id==pid,Finding.status=='confirmed')).all() if (f.code.startswith('missing_') and ('metadata' in capabilities if f.code!='missing_alt' else 'accessibility' in capabilities))]
            if not matches: raise ProjectHuntError('no confirmed finding matching established capability')
            f=matches[0]
            result={'problem':f.description,'finding_id':f.id,'evidence':f.evidence,'solution':f'Correct {f.description.lower()} and verify the result','deliverables':['A targeted fix','A before/after check'],'assumptions':['Owner can grant site access'],'risks':['Underlying platform may constrain the fix'],'budget':'Estimate pending discovery'}
            opp.scope=result; opp.stage='Qualified'; p.status='Qualified'; db.add(Event(prospect_id=pid,kind='scope_prepared',detail=f.id))
            return result
    def verify_contact(self,pid,source_url:str):
        if urlsplit(source_url).scheme not in ('http','https'): raise ProjectHuntError('contact source URL required')
        with self.sessions.begin() as db:
            p=db.get(Prospect,pid)
            if not p or not p.email: raise ProjectHuntError('contact unavailable')
            p.contact_verified=True; p.contact_source_url=source_url
            db.add(Event(prospect_id=pid,kind='contact_reviewed',detail=source_url))
        return {'verified':True,'source_url':source_url,'meaning':'User attested to observing the address at this source; delivery is unverified'}
    def suppress(self,email,reason='opt_out'):
        email=email.strip().lower()
        if not EMAIL.fullmatch(email): raise ProjectHuntError('invalid email')
        with self.sessions.begin() as db: db.merge(Suppression(email=email,reason=reason)); db.add(Event(kind='suppressed',detail=email))
        return {'suppressed':email}
    def draft(self,pid):
        with self.sessions.begin() as db:
            p=db.get(Prospect,pid)
            if not p: raise ProjectHuntError('prospect not found')
            opp=db.scalar(select(Opportunity).where(Opportunity.prospect_id==pid))
            if not opp.scope: raise ProjectHuntError('scope required')
            if not p.email or not p.contact_verified: raise ProjectHuntError('reviewed contact required')
            if db.get(Suppression,p.email): raise ProjectHuntError('contact suppressed')
            if opp.sent_at or db.scalar(select(Event.id).where(Event.prospect_id==pid,Event.kind=='sent')): raise ProjectHuntError('duplicate outreach')
            if opp.draft: raise ProjectHuntError('draft already exists; review existing draft')
            scope=opp.scope
            body=f"To: {p.email}\nSubject: Website note for {p.name}\n\nHello,\n\nI noticed {scope['problem'].lower()} on {scope['evidence']['url']}. I can make a targeted fix and share a before/after check. Would it be useful to discuss?\n\nAmar Jaleel\nAmar Digital Systems\nhttps://amarjaleel.me"
            opp.draft=body; opp.recipient=p.email; opp.stage='Draft Prepared'; p.status='Draft Prepared'
            db.add(Event(prospect_id=pid,kind='draft_prepared',detail='local draft; not sent'))
            return {'draft':body,'sent':False,'opportunity_id':opp.id}
    def pipeline(self):
        with self.sessions() as db:
            return [{'id':o.id,'prospect_id':o.prospect_id,'stage':o.stage,'scope':o.scope,'draft':o.draft,'sent_at':o.sent_at.isoformat() if o.sent_at else None} for o in db.scalars(select(Opportunity)).all()]
    def report(self):
        with self.sessions() as db:
            count=lambda kind:db.scalar(select(func.count()).select_from(Event).where(Event.kind==kind))
            return {'discovered':count('discovered'),'verified':count('verified'),'duplicates_rejected':count('duplicate'),'drafts_prepared':count('draft_prepared'),'emails_sent':count('sent'),'confirmed_revenue_cents':0,'reply_rate':'insufficient data' if not count('sent') else {'numerator':count('reply'),'denominator':count('sent')}}
