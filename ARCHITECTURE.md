# Architecture (0.2.0)

FastAPI HTTP routes and the MCP stdio adapter call the same `ProjectHunt` service. SQLAlchemy persists prospects, findings, opportunities, suppressions and event history. Docker Compose starts PostgreSQL 16; SQLite is used only in local tests. `BeautifulSoup` parses a bounded static HTML response. No AI API is called. The MCP process calls FastAPI with a bearer key loaded from a private local file, and cannot send mail.

This is single-operator software. PostgreSQL schema initialization uses `create_all`, so production migrations and account-scoped authorization are required before shared deployment. Safe hosted auditing needs network egress isolation and validated DNS pinning. ChatGPT cloud integration additionally needs authenticated remote MCP and OAuth; packaged stdio MCP has only been verified locally.
