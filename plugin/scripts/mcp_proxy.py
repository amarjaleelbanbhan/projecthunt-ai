"""Local stdio entrypoint; requires installed projecthunt package and MCP dependencies."""
import os
from pathlib import Path
from urllib.parse import urlsplit

data=Path(os.environ['PLUGIN_DATA'])
secret=data/'projecthunt-api-key'
if not secret.is_file() or (secret.stat().st_mode & 0o077):
    raise SystemExit('Create a 0600 projecthunt-api-key file in PLUGIN_DATA')
os.environ['PROJECTHUNT_API_KEY']=secret.read_text().strip()
url_file=data/'backend-url'
if url_file.exists():
    url=url_file.read_text().strip().rstrip('/')
    parsed=urlsplit(url)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1')):
        raise SystemExit('Backend must use HTTPS outside loopback')
    os.environ['PROJECTHUNT_API_BASE']=url
from projecthunt.mcp_server import mcp
mcp.run(transport='stdio')
