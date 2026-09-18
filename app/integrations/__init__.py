"""Outbound connections to external systems (spec: JIRA/WooCommerce/SMTP/
custom REST APIs), configured per-tenant via `Integration` rows
(app.domain.models.integration) managed through
`POST/GET/PUT/DELETE /api/v1/admin/integrations` (ADMIN-only).

Every client here takes an `Integration` row and does exactly one thing -
`JiraClient` creates issues/comments, `WooCommerceClient` looks up orders,
`EmailClient` sends mail - all built on `build_http_client` (base.py),
which resolves the stored, encrypted credentials into the right auth
shape (api key header / bearer / basic) for a plain httpx call. None of
this is wired into the LLM's autonomous tool-calling loop - JIRA
auto-creation on escalation and the post-decision comment are
deterministic Python triggers (see app.integrations.hooks), and
WooCommerce lookup is staff-triggered from the ticket detail UI - see
docs/SECURITY.md for why.
"""
