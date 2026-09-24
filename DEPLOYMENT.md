# Secure deployment and recovery (0.3 development branch)

## Boundaries

Run the API and PostgreSQL on private Docker networks. Compose publishes API and the optional MCP gateway on loopback only. The database has no host port and is on an internal network. The audit path pins the socket to a validated public DNS answer, sends one bounded GET with no redirects, and uses a validating TLS context. A 120-request/minute API limit is local to one process; a database-backed reservation limits audits to 20/hour. Do not scale API workers without a shared general request limiter. Put an outbound firewall or egress proxy in front of audit workloads for defense in depth; Docker Compose alone cannot guarantee a strict public-IP-only egress policy.

## Secrets and identity

Provide long, randomly generated `POSTGRES_PASSWORD` and `PROJECTHUNT_API_KEY` from a secret manager. Never commit `.env` or pass credentials through an MCP tool argument. Run with a database account restricted to the ProjectHunt database. Rotate the API key by changing both the private API and remote MCP service at the same time. Rotate the DB password in PostgreSQL and the application secret together; restart services and verify health. Back up PostgreSQL with encrypted storage and access restricted to the operator. Schema currently uses `create_all`; take a backup and introduce versioned migrations before upgrades to an existing production database.

Configure an HTTPS OAuth 2.1 authorization server that supports ChatGPT's authorization-code flow with PKCE S256, publishes authorization metadata, and issues RS256 access tokens with `iss`, `aud`, `sub`, `scope`, `iat`, `exp`. The owner `sub` must be the only account authorized for this single-operator build. The `aud` must exactly equal the public MCP resource URL ending `/mcp`; scope must contain `projecthunt:access`. The JWKS URL must use HTTPS on the issuer's hostname. The gateway fetches and caches signing keys; it does not accept unsigned, symmetric, or wrong-audience tokens. ChatGPT's auth linking must be verified with the actual configured provider before use.

## Start privately

1. Copy `.env.example` to `.env` and set `PROJECTHUNT_API_KEY` and `POSTGRES_PASSWORD`.
2. Set `OAUTH_ISSUER`, `JWT_JWKS_URL`, `PROJECTHUNT_OWNER_SUB`, and `MCP_PUBLIC_URL=https://YOUR_DOMAIN/mcp` in `.env`.
3. `docker compose --profile remote up --build -d`. A missing or invalid OAuth configuration causes the MCP gateway to fail at startup.
4. Terminate TLS at a trusted reverse proxy and route **only** `/mcp` and `/.well-known/oauth-protected-resource/mcp` to `127.0.0.1:8001`. Keep port 8000 private. Configure reverse-proxy rate limits, request-size limits, TLS certificates, and a firewall that blocks private/metadata IP egress from the API's audit path.
5. Check an unauthenticated POST `/mcp` returns 401 with a `WWW-Authenticate` challenge; inspect the protected-resource metadata and confirm it advertises the exact MCP resource and issuer. Link with the identity provider, then use an MCP client to initialize, list tools and call `get_performance_report` with a valid token. Confirm a different user and wrong audience get 401.
6. Register the HTTPS MCP server through ChatGPT developer mode, verify OAuth linking and discovered tool schemas, and run the synthetic workflow in ChatGPT. Only after this live test update the existing plugin with the real connection mapping and version 0.3.0. The current plugin remains 0.2.0 until those steps pass.

## Secure MCP Tunnel alternative

The private MCP gateway may be reached through an OpenAI Secure MCP Tunnel instead of public HTTPS. Run the supported tunnel client beside port 8001 using credentials provisioned in Platform tunnel settings, confirm its health, then select the tunnel in ChatGPT's developer-mode connection. A tunnel is a transport path and does not replace app authorization or the operator identity check. No tunnel ID or runtime key is included in the repository. Keep the tunnel client running during discovery and calls. Follow the official tunnel guide for the client version and workspace permissions.

## Recovery

- MCP 401: check issuer metadata, exact `aud`, scopes, `sub`, token expiry, JWKS rotation, and gateway time synchronization. Never disable token checks to debug.
- MCP unavailable: verify gateway logs, reverse-proxy TLS, `/mcp` route, and tunnel-client health when applicable. Keep the private API inaccessible directly.
- Audit failures: inspect `audit_failed` event and check public DNS, TLS and egress policy. The prospect returns to `Discovered`; failed attempts still count toward the hourly quota.
- Database unavailable: verify DB health and the private network. Restore from a tested encrypted backup. Do not reinitialize a populated database to recover access.
- Revoke access: disable the owner's IdP account or scope, rotate internal API key, and remove or disable the ChatGPT MCP connection. Token TTL and JWKS cache affect revocation latency.

## Current verification

Local automated tests cover DNS pinning, blocking private/mixed DNS, redirects, oversize responses, rate-limited audit reservations, OAuth JWT validation, authenticated HTTP MCP calls through the API, and SQLite persistence. CI adds PostgreSQL persistence. A real ChatGPT session, remote endpoint, and identity-provider link remain unverified until provisioned.
