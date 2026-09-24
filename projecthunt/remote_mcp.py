"""OAuth-protected streamable HTTP MCP gateway for an already configured identity provider.

This module refuses startup without a trusted issuer, JWKS, audience and owner subject.
A TLS terminator must serve MCP_PUBLIC_URL over HTTPS. The API remains on loopback.
"""
import asyncio
import os
from urllib.parse import urlsplit

import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl
from .mcp_server import mcp as local_tools

REQUIRED_SCOPE='projecthunt:access'

class JWTVerifier:
    def __init__(self,issuer:str,jwks_url:str,resource:str,owner_sub:str):
        a=urlsplit(issuer);b=urlsplit(jwks_url);c=urlsplit(resource)
        if (a.scheme!='https' or b.scheme!='https' or c.scheme!='https'
                or not a.hostname or a.hostname!=b.hostname or not c.hostname
                or not resource.endswith('/mcp') or not owner_sub):
            raise ValueError('HTTPS issuer/JWKS on one host, HTTPS MCP resource and owner subject are required')
        self.issuer=issuer.rstrip('/');self.resource=resource;self.owner_sub=owner_sub
        self.keys=jwt.PyJWKClient(jwks_url,cache_keys=True)
    def _verify(self,token:str)->AccessToken|None:
        try:
            key=self.keys.get_signing_key_from_jwt(token)
            claims=jwt.decode(token,key.key,algorithms=['RS256'],issuer=self.issuer,
                              audience=self.resource,leeway=30,
                              options={'require':['exp','iat','iss','aud','sub']})
            if claims['sub']!=self.owner_sub: return None
            scope=claims.get('scope','')
            if not isinstance(scope,str):return None
            scopes=scope.split()
            if REQUIRED_SCOPE not in scopes:return None
            return AccessToken(token=token,client_id=claims.get('client_id','chatgpt'),
                               scopes=scopes,expires_at=claims['exp'],resource=self.resource,
                               subject=claims['sub'])
        except (jwt.PyJWTError,ValueError,TypeError):return None
    async def verify_token(self,token:str)->AccessToken|None:
        # JWKS fetch is blocking and deliberately configured by the operator.
        return await asyncio.to_thread(self._verify,token)

def create_app():
    issuer=os.environ['OAUTH_ISSUER'].rstrip('/')
    resource=os.environ['MCP_PUBLIC_URL'].rstrip('/')
    verifier=JWTVerifier(issuer,os.environ['JWT_JWKS_URL'],resource,os.environ['PROJECTHUNT_OWNER_SUB'])
    # Reuse the registered tool objects; FastMCP's public list_tools is async.
    server=FastMCP('projecthunt-ai',tools=local_tools._tool_manager.list_tools(),token_verifier=verifier,
                   auth=AuthSettings(issuer_url=AnyHttpUrl(issuer),resource_server_url=AnyHttpUrl(resource),
                                     required_scopes=[REQUIRED_SCOPE],validate_token_resource=True),
                   stateless_http=True,json_response=True,max_request_body_size=2_100_000,
                   host='0.0.0.0',streamable_http_path='/mcp')
    return server.streamable_http_app()

# Run with `uvicorn projecthunt.remote_mcp:create_app --factory`.
# The factory fails closed when its required OAuth configuration is absent.
