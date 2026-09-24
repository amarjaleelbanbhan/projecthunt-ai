"""Single-operator local API. Do not expose publicly without user-scoped OAuth."""
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from .service import ProjectHunt, ProjectHuntError, fetch_audit

app=FastAPI(title='ProjectHunt AI',version='0.3.0')
_service=None
_rate_lock=threading.Lock()
_requests=defaultdict(deque)

@app.middleware('http')
async def throttle(request,call_next):
    # One worker is required; deploy behind an additional gateway limit.
    identity=request.client.host if request.client else 'unknown'
    now=time.monotonic()
    with _rate_lock:
        q=_requests[identity]
        while q and q[0]<=now-60: q.popleft()
        if len(q)>=120:
            return JSONResponse({'detail':'request limit reached'},status_code=429,headers={'Retry-After':'60'})
        q.append(now)
    return await call_next(request)

def service():
    global _service
    if _service is None:
        _service=ProjectHunt(os.environ.get('DATABASE_URL','sqlite:///./projecthunt.db'))
    return _service

def auth(authorization: str | None=Header(default=None)):
    key=os.environ.get('PROJECTHUNT_API_KEY')
    if not key or not authorization or not secrets.compare_digest(authorization,'Bearer '+key):
        raise HTTPException(401,'Authentication required')

def handle(fn):
    try: return fn()
    except ProjectHuntError as exc: raise HTTPException(400,str(exc)) from exc

class ScopeRequest(BaseModel):
    capabilities: list[str] = Field(min_length=1)
class ContactReview(BaseModel):
    source_url: str
class SuppressRequest(BaseModel):
    email: str
    reason: str = 'opt_out'

@app.post('/prospects/import',dependencies=[Depends(auth)])
async def import_csv(file:UploadFile, svc:ProjectHunt=Depends(service)):
    content=await file.read(2_000_001)
    if len(content)>2_000_000: raise HTTPException(413,'CSV exceeds 2 MB')
    return handle(lambda: svc.import_csv(content.decode('utf-8-sig')))

@app.get('/prospects',dependencies=[Depends(auth)])
def prospects(svc:ProjectHunt=Depends(service)): return svc.prospects()

@app.get('/prospects/{pid}',dependencies=[Depends(auth)])
def prospect(pid:str,svc:ProjectHunt=Depends(service)): return handle(lambda:svc.get(pid))

@app.post('/prospects/{pid}/audit',dependencies=[Depends(auth)])
def audit(pid:str,svc:ProjectHunt=Depends(service)):
    def run():
        p=svc.get(pid)
        svc.reserve_audit(pid)
        try:
            report=fetch_audit(p['website'])
            return svc.save_audit(pid,report)
        except Exception as exc:
            svc.fail_audit(pid,exc)
            raise
    return handle(run)

@app.get('/prospects/{pid}/findings',dependencies=[Depends(auth)])
def findings(pid:str,svc:ProjectHunt=Depends(service)):
    return handle(lambda:svc.findings(pid))

@app.post('/prospects/{pid}/scope',dependencies=[Depends(auth)])
def scope(pid:str,request:ScopeRequest,svc:ProjectHunt=Depends(service)):
    return handle(lambda:svc.scope(pid,request.capabilities))

@app.post('/prospects/{pid}/contact-review',dependencies=[Depends(auth)])
def contact_review(pid:str,request:ContactReview,svc:ProjectHunt=Depends(service)):
    return handle(lambda:svc.verify_contact(pid,request.source_url))

@app.post('/suppression',dependencies=[Depends(auth)])
def suppress(request:SuppressRequest,svc:ProjectHunt=Depends(service)):
    return handle(lambda:svc.suppress(request.email,request.reason))

@app.post('/prospects/{pid}/draft',dependencies=[Depends(auth)])
def draft(pid:str,svc:ProjectHunt=Depends(service)):
    return handle(lambda:svc.draft(pid))

@app.get('/pipeline',dependencies=[Depends(auth)])
def pipeline(svc:ProjectHunt=Depends(service)): return svc.pipeline()

@app.get('/performance',dependencies=[Depends(auth)])
def performance(svc:ProjectHunt=Depends(service)): return svc.report()
