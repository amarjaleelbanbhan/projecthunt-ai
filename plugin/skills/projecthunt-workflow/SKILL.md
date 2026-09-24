---
name: projecthunt-workflow
description: Use configured ProjectHunt MCP tools to import sourced CSV prospects, audit public HTML, scope evidenced fixes, and prepare local outreach drafts.
---
# ProjectHunt workflow

Use `import_prospects` for sourced CSV, `search_prospects` to select a real ID, `audit_website` to persist a static HTML report, and `prepare_proposal` only when confirmed findings match the user's stated capability. Use `review_contact` only if the user has actually checked the source URL and saw the contact address there. Before `create_email_draft`, confirm recipient and suppression policy; the tool records a local draft and never sends. Use `get_opportunities` and `get_performance_report` for persisted results. Cite the source URL and exact finding; distinguish possible issues from confirmed findings. If the MCP server is unconfigured or unreachable, say so. Never claim delivered email, replies, clients, or revenue from a draft.
