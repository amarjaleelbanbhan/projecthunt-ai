"""Local MCP tools calling the same REST API. No outreach send tool exists."""
import os
import httpx
from mcp.server.fastmcp import FastMCP

mcp=FastMCP('projecthunt-ai')
BASE=os.environ.get('PROJECTHUNT_API_BASE','http://127.0.0.1:8000').rstrip('/')

def request(method,path,*,data=None,files=None):
    key=os.environ.get('PROJECTHUNT_API_KEY')
    if not key: raise ValueError('PROJECTHUNT_API_KEY is required')
    with httpx.Client(base_url=BASE,timeout=40) as client:
        response=client.request(method,path,headers={'Authorization':'Bearer '+key},json=data,files=files)
        response.raise_for_status()
        return response.json()

@mcp.tool()
def import_prospects(csv_text:str)->dict:
    """Import user-provided sourced CSV: name,website,source_url and optional email/location/industry."""
    return request('POST','/prospects/import',files={'file':('prospects.csv',csv_text,'text/csv')})

@mcp.tool()
def search_prospects()->list[dict]:
    """List persisted prospects and their source URLs."""
    return request('GET','/prospects')

@mcp.tool()
def audit_website(prospect_id:str)->dict:
    """Audit a selected sourced prospect's public website and save static HTML findings."""
    return request('POST',f'/prospects/{prospect_id}/audit')

@mcp.tool()
def get_opportunities()->list[dict]:
    """List opportunity stage, saved scope, and any local draft."""
    return request('GET','/pipeline')

@mcp.tool()
def prepare_proposal(prospect_id:str,capabilities:list[str])->dict:
    """Generate scope from confirmed findings matching the user's stated metadata/accessibility capability."""
    return request('POST',f'/prospects/{prospect_id}/scope',data={'capabilities':capabilities})

@mcp.tool()
def review_contact(prospect_id:str,source_url:str)->dict:
    """Attest that the existing CSV contact address was personally observed at a source URL; this does not verify delivery."""
    return request('POST',f'/prospects/{prospect_id}/contact-review',data={'source_url':source_url})

@mcp.tool()
def create_email_draft(prospect_id:str)->dict:
    """Prepare a local email draft after contact review and suppression checks. No email is sent."""
    return request('POST',f'/prospects/{prospect_id}/draft')

@mcp.tool()
def suppress_contact(email:str,reason:str='opt_out')->dict:
    """Prevent future drafts for an address; keep reason in the local audit history."""
    return request('POST','/suppression',data={'email':email,'reason':reason})

@mcp.tool()
def get_performance_report()->dict:
    """Return counters derived from persisted events and no invented revenue."""
    return request('GET','/performance')

if __name__=='__main__': mcp.run(transport='stdio')
