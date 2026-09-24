# Security

Report vulnerabilities privately through GitHub security advisories. Never commit credentials or customer records. The API uses a single operator bearer key and is bound to loopback in Compose. The separate remote MCP gateway requires an HTTPS OAuth issuer, verifies RS256 JWT signatures, issuer, audience, expiry, scope and exact owner subject, and fails closed when unconfigured. It does not turn the API into a public endpoint.

The audit fetcher rejects private or mixed DNS results, internal hostnames, redirects, nonstandard ports and oversized HTML; it pins the outbound socket to a previously checked address while retaining the hostname for TLS verification. API requests are limited per source IP in one process; audit attempts have a database-backed hourly quota. A public-IP-only egress firewall remains recommended for defense in depth. The contact-review endpoint records operator attestation, not independent validation. See DEPLOYMENT.md for configuration and recovery.
