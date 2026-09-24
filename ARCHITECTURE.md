# Architecture (0.3 development)

The existing FastAPI application, SQLAlchemy persistence, PostgreSQL Compose service, and nine MCP tools remain in place. A second FastMCP server reuses those tool objects over stateless Streamable HTTP. It validates OAuth access tokens against an operator-configured HTTPS issuer/JWKS, checks issuer, exact resource audience, scope, expiry and owner subject, then calls the API through a private bearer-key channel. Missing configuration fails gateway startup. The API and MCP bind to loopback in Compose; PostgreSQL is isolated on an internal Docker network.

The public HTML audit resolves DNS once, rejects any private address, and connects a socket to a selected validated IP while preserving the original hostname for HTTP Host, TLS SNI and certificate validation. Redirects and bodies over 1 MB are rejected. The API limits requests to 120/minute per source IP in one process and reserves at most 20 audits/hour in the database. PostgreSQL advisory locking serializes audit quota reservations. The API is single operator; there is no email send operation or paid AI dependency.

A reverse proxy, TLS certificate, trusted OAuth provider and either HTTPS ingress or a provisioned Secure MCP Tunnel are deployment dependencies, not part of this repository. See DEPLOYMENT.md for the exact boundaries.
