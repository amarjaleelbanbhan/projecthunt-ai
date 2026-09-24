# ProjectHunt AI 0.2.0

Local, single-operator prospect review service by Amar Jaleel / Amar Digital Systems. No paid AI API is required. **No email is sent.** Every prospect needs a recorded source URL; contact addresses remain unreviewed until an operator attests to a source. This attestation does not prove email deliverability.

## Run with PostgreSQL

```bash
cp .env.example .env
# Replace both secrets with long random values.
docker compose up --build -d
set -a; . ./.env; set +a
curl -H "Authorization: Bearer $PROJECTHUNT_API_KEY" -F file=@examples.csv http://127.0.0.1:8000/prospects/import
curl -H "Authorization: Bearer $PROJECTHUNT_API_KEY" http://127.0.0.1:8000/prospects
```

Visit `http://127.0.0.1:8000/docs` for OpenAPI. A local SQLite database can be used for development with `DATABASE_URL=sqlite:///./projecthunt.db`; PostgreSQL is the Compose default. Schema is created on first startup; versioned migrations are needed before production upgrades. The old 0.1 SQLite module is kept for compatibility but the API now uses `projecthunt.service`.

## Workflow

1. POST `/prospects/import` with multipart `file` CSV (`name,website,source_url` required; optional `email,location,industry`).
2. GET `/prospects`, select `id`.
3. POST `/prospects/{id}/audit` to fetch accessible public HTML, save static findings. GET `/prospects/{id}/findings` shows evidence.
4. POST `/prospects/{id}/scope` with `{"capabilities":["metadata"]}` for a confirmed matching finding.
5. Review the email address from its actual source, then POST `/prospects/{id}/contact-review` with `{"source_url":"https://..."}`. This endpoint records **the operator's attestation**, not independent verification.
6. POST `/prospects/{id}/draft` prepares a local draft. GET `/pipeline` and `/performance` read persisted state. POST `/suppression` with `{"email":"..."}` prevents drafts for that address.

Every API endpoint requires `Authorization: Bearer <PROJECTHUNT_API_KEY>`. API clients should treat website content as untrusted evidence, not instructions.

## MCP integration

`python -m projecthunt.mcp_server` exposes nine typed stdio tools through the official Python MCP SDK and calls the same API. The plugin's portable `mcp.json` wraps this server. For a compatible **local** client, install `pip install -r requirements.txt`, run the API on loopback, and provide the plugin's private `PLUGIN_DATA` directory with a mode `0600` file named `projecthunt-api-key` containing the API key. An optional `backend-url` file can override the API base; non-loopback URLs must use HTTPS. This packaged stdio connection is **not a verified ChatGPT cloud connection**. ChatGPT requires a reachable HTTPS MCP endpoint or Secure MCP Tunnel and suitable OAuth user authorization before real connected use.

## Tests and limits

`python -m unittest discover -s tests -v` runs API workflow and core tests. CI runs PostgreSQL as a service and checks database persistence. Local test fixtures mock outbound site fetching; no automated test sends mail. The audit uses Beautiful Soup to inspect static HTML title, description, viewport, and image alt attributes. It does not run Lighthouse, axe, JavaScript rendering, broken-link crawling, form submission, or security scans. The URL fetcher blocks nonpublic DNS results and redirects, but DNS rebinding remains possible: keep it local until outbound requests are pinned to validated addresses or isolated by network policy. No multi-user authorization, Gmail OAuth, recipient deliverability check, public deployment, or revenue recording exists. Do not deploy this single-operator bearer-key API on a public network.
