# API

Base URL: `http://localhost:8000`. All `/api/v1/support/*` endpoints except
`/tickets/*` require `Authorization: Bearer <customer JWT>` (see
`app.security.auth.create_access_token`; `make seed` prints working tokens).
Ticket endpoints require `Authorization: Bearer <staff JWT>` obtained from
`POST /api/v1/staff/login` instead (see `docs/SECURITY.md` for why these
are separate, non-interchangeable tokens).

Every token (customer and staff) carries a `tenant_id` claim (spec §43,
default `"default"` for the zero-setup single-tenant case) - all data
returned by any endpoint is scoped to the caller's tenant; there is no
parameter to read across tenants. See "Multi-tenancy & tenant isolation"
in `docs/SECURITY.md`.

## Customer auth

```
POST /api/v1/customers/register
  body: {"email": "...", "password": "...", "full_name": "..."}
  -> 201 {"access_token": "...", "customer_id": "...", "full_name": "..."}
  -> 400 if the email is already registered

POST /api/v1/customers/login
  body: {"email": "...", "password": "..."}
  -> 200 {"access_token": "...", "customer_id": "...", "full_name": "..."}
  -> 401 on wrong email or password (same error either way)

GET /api/v1/customers/me   (Authorization: Bearer <customer JWT>)
  -> 200 {id, email, full_name, tier}
```

Self-service registration always creates the customer in the default
tenant - this is the public storefront's auth, not a tenant-provisioning
flow (see docs/SECURITY.md). `make seed` also seeds two customers
(`alice@example.com`/`bob@example.com`, password `dev-customer-password`)
so the frontend has accounts to log in with immediately.

## Health

```
GET /api/v1/health   -> {"status": "ok"}
GET /api/v1/ready    -> {"status": "ready"}   # also checks DB connectivity
```

## Conversations

```
POST /api/v1/support/conversations
  body: {"channel": "web"}
  -> 201 {id, customer_id, channel, status, intent, priority, created_at}

GET /api/v1/support/conversations/{id}
  -> {id, customer_id, channel, status, intent, priority, created_at}

GET /api/v1/support/conversations/{id}/messages
  -> [{role, content, created_at}, ...]

GET /api/v1/support/ws/conversations/{id}?token=<customer JWT>   (spec: Phase 10.3)
  websocket - a browser WebSocket can't set a custom Authorization
  header, so the JWT travels as a query param instead of the usual
  Bearer header. Server-push only (the client never sends anything the
  server reads). Two event sources push a JSON message while connected:
    - {"event", "order_id", "ticket_id"} - a storefront webhook
      correlates to this conversation (see "Inbound storefront webhooks"
      below)
    - {"event": "ticket_decision", "workflow_run_id", "approved"} - a
      staff member approves/rejects a paused ticket on this conversation
  both documented in docs/ARCHITECTURE.md's "Real-time push to an active
  conversation". Closes with 4401 on a missing/invalid/expired token,
  4404 if the conversation doesn't exist or belongs to a different
  customer. Single-API-instance only today - see docs/DEPLOYMENT.md.
```

## Messages (the main endpoint)

```
POST /api/v1/support/messages
  body: {
    "conversation_id": "conv_123",   # create your own id; first use creates the conversation
    "message_id": "msg_1",           # unique per message
    "message": "Where is my order?",
    "channel": "web"
  }
  -> 200 {
    "conversation_id": "conv_123",
    "workflow_run_id": "...",
    "status": "resolved" | "escalated" | "awaiting_approval",
    "response": "..." | null,        # null only when status == "awaiting_approval"
    "requires_human": false,
    "ticket_id": null | "..."        # set when status == "awaiting_approval" or escalated
  }
```

`status` meanings:

- `resolved` - the AI answered directly; no human involvement needed.
- `escalated` - a `SupportTicket` was filed for a human to review (security/
  fraud/legal, low-confidence classification, no reliable knowledge found,
  or repeated failed resolution). The customer still gets `response` - an
  honest acknowledgment, not a resolution.
- `awaiting_approval` - a high-risk action (a refund, or - spec: Phase 6,
  generalized in Phase 7 - a proposed external tool call against a
  connected MCP server or OpenAPI-described REST API) was proposed and is
  paused on a human approve/reject decision. `response` is `null` until
  that decision is made; poll `GET /tickets/{ticket_id}` or drive it via
  the approve/reject endpoints below. An external tool call is only ever
  proposed as a fallback - when the intent has no built-in resolver and
  knowledge-base retrieval found nothing - and is only ever executed
  after approval, never before (see docs/SECURITY.md's "External tool
  calls" section and `app.agents.external_tools`).

Commerce intents (order status/cancel/refund/returns/payment
failure/subscription, plus - spec: Phase 8.3 - subscription plan
changes, address changes, payment retries, and exchanges) all go
through this same endpoint; which of them have an internal DB-backed
resolver vs. storefront-only handling is documented in
`docs/ARCHITECTURE.md`'s "Expanded commerce scenarios" - the API shape
itself doesn't change per intent.

### Try the sample scenarios (spec §43)

```bash
TOKEN="<paste a token from make seed>"

# Order status - resolved immediately
curl -X POST localhost:8000/api/v1/support/messages -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"c1","message_id":"m1","message":"Where is my order?","channel":"web"}'

# Refund - two turns, then human approval
curl -X POST localhost:8000/api/v1/support/messages -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"c2","message_id":"m1","message":"The product arrived damaged. I want my money back.","channel":"web"}'
curl -X POST localhost:8000/api/v1/support/messages -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"c2","message_id":"m2","message":"yes","channel":"web"}'
# -> status: "awaiting_approval", ticket_id: "..."

# Security - always escalates, never looks up account details
curl -X POST localhost:8000/api/v1/support/messages -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"c3","message_id":"m1","message":"I received a login notification that was not me.","channel":"web"}'

# Out of scope - never hallucinates, escalates instead
curl -X POST localhost:8000/api/v1/support/messages -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"c4","message_id":"m1","message":"Can you explain your company'"'"'s quantum computing strategy?","channel":"web"}'
```

## Staff login & user management

```
POST /api/v1/staff/login
  body: {"username": "agent_jane", "password": "..."}
  -> 200 {"access_token": "...", "role": "SUPPORT_AGENT"}
  -> 401 on wrong username or password (same error either way)
```

`make seed` creates one seeded staff user per role (spec §36:
`agent_jane`/`SUPPORT_AGENT`, `manager_mo`/`SUPPORT_MANAGER`,
`admin_priya`/`ADMIN`, `security_sam`/`SECURITY_AGENT`, all password
`dev-agent-password`) and prints their credentials. Rate-limited to 5
attempts per 5 minutes per username.

```
GET  /api/v1/staff/users   (ADMIN role only)   -> [{id, username, role, is_active, created_at}, ...]
POST /api/v1/staff/users   (ADMIN role only)
  body: {"username": "new_agent", "password": "...", "role": "SUPPORT_AGENT"}
  -> 201 {id, username, role, is_active, created_at}
  -> 403 if the caller's token role isn't ADMIN
  -> 400 if the username is already taken
```

Creates a new staff account, in the calling admin's own tenant, with any
`StaffRole`. This is how RBAC is exercised beyond the seeded accounts -
see "RBAC" in `docs/SECURITY.md`.

## Runtime settings (ADMIN only, spec §32/§43)

```
GET    /api/v1/admin/settings          -> [{key, value, source, updated_by, updated_at}, ...]
PUT    /api/v1/admin/settings/{key}    body: {"value": ...}   -> 200 {key, value, source: "override", updated_by, updated_at}
DELETE /api/v1/admin/settings/{key}    -> 204 (clears the override, falls back to the env default)
```

Lets an `ADMIN` tune a small allow-list of operational settings for their
own tenant without an env var change or redeploy:
`mock_llm`, `default_llm_provider`, `fallback_llm_provider`,
`confidence_intent`, `confidence_retrieval`, `rate_limit_per_window`,
`rate_limit_window_seconds`, `llm_budget_usd_per_run`,
`escalation_max_failed_attempts`. `GET` returns every allow-listed key
whether or not it has been overridden - `source` is `"override"` (this
tenant has set it) or `"default"` (falling back to the env var). A change
takes effect on the *next* request in this tenant, no restart needed.

`PUT`/`DELETE` on a key outside the allow-list returns `400
VALIDATION_ERROR` - this is a deliberate, hardcoded boundary, not a
missing feature: secrets (`GOOGLE_API_KEY`, `JWT_SECRET`, `DATABASE_URL`,
...) can never be set this way. See "DB-backed runtime settings" in
`docs/SECURITY.md`.

```bash
# Example: cap this tenant's per-run LLM spend at $0.05 without a redeploy
curl -X PUT localhost:8000/api/v1/admin/settings/llm_budget_usd_per_run \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"value": 0.05}'
```

## Tickets (staff-only, `Authorization: Bearer <staff JWT>`)

```
GET  /api/v1/support/tickets?status=open&limit=50&offset=0   -> [TicketResponse, ...]
GET  /api/v1/support/tickets/{id}
GET  /api/v1/support/tickets/{id}/trace   -> TicketTraceResponse   (spec: Phase 11)
POST /api/v1/support/tickets/{id}/approve   body: {"workflow_run_id": "...", "arguments": {...}?}
POST /api/v1/support/tickets/{id}/reject    body: {"workflow_run_id": "...", "reason": "..."}
```

**`GET .../trace`** - "what did the agent actually do" for the run that
produced this ticket: `{"workflow_run_id", "events": [...], "tool_executions":
[...]}`. `events` is every node the workflow graph passed through, in
order, with its status, duration, and a curated subset of what it
decided (intent, priority, escalation reason, tool calls proposed, etc. -
never full response text). `tool_executions` is every real tool call
made, internal or external (MCP/OpenAPI), with PII-redacted arguments
and results. Returns `{"workflow_run_id": "", "events": [], "tool_executions": []}`
for a ticket with no `workflow_run_id` at all (e.g. one filed by an
inbound webhook, spec: Phase 8.4). Both underlying tables existed for
this exact purpose from early in this project's history but were never
populated (`workflow_events.data`) or written to for external tool calls
(`tool_executions`) until this phase - see `docs/SECURITY.md`'s "Audit
trail" section.

**`TicketResponse.pending_call`** (spec: Phase 8.2) - `{"integration_name",
"tool_name", "arguments"}` for an external-tool-call ticket (an MCP or
OpenAPI proposal awaiting approval), `null` for a refund ticket (which
has no external call to preview). This is the same data that used to
only be visible flattened into free-text `summary`/`actions_taken` -
structured here so a UI can render an editable form instead of parsing
prose.

**`approve`'s optional `arguments`** (spec: Phase 8.2) lets staff override
some or all of `pending_call.arguments` before the call actually runs -
only the keys you send are merged in (unset keys keep the AI-proposed
value), and the *merged* result is re-validated against the tool's real
JSON Schema before dispatch (a bad override is rejected with the ticket
reopened, exactly like a failed call - see below - never silently
coerced or allowed to reach the external system unvalidated). Ignored
entirely for a refund ticket (`pending_call` is `null`, so there is
nothing to merge into).

**`TicketResponse.execution_result`** (spec: Phase 8.2) - the real
API/MCP response once an external-tool proposal is approved and
executed (`{"error": "..."}` on failure), `null` until then and always
`null` for a refund ticket. Previously this was discarded after being
folded into response text - now it's inspectable on the ticket itself.

The list endpoint is the staff queue view - it's automatically scoped to
the caller's role the same way the per-ticket approve/reject check is
(`app.config.policies.ticket_queue_filter_for_role`): a `SUPPORT_AGENT`/
`SUPPORT_MANAGER` never sees a `SECURITY`/`FRAUD`/`LEGAL` ticket in the
list at all, a `SECURITY_AGENT` sees only those, and `ADMIN` sees every
ticket. `status` is optional (omit it to see tickets in any status).

`workflow_run_id` comes from the `/messages` response that produced
`status: "awaiting_approval"`. Approve/reject resume the paused LangGraph
run (see `docs/ARCHITECTURE.md`) and write an `audit_logs` entry.
`approved_by` is always set to the authenticated staff id (not a
client-supplied name - see `docs/SECURITY.md`). The ticket's `status`
update is where an approval's *outcome* matters, not just the decision:
a clean approval sets `resolved`, a reject sets `rejected`, but an
approval whose action then **fails during execution** (spec: Phase 6/7 -
an approved MCP or OpenAPI tool call erroring, or its integration having
been disabled/removed between proposal and approval) reopens the ticket to
`open` instead of `resolved`, with `reason_for_escalation` updated to
explain why - a failed action is exactly the kind of anomaly that needs a
human to see it in the queue, not a ticket that silently reads "resolved"
while the customer received an apology. Note this does **not** mean
clicking "Approve" again retries the call: the underlying LangGraph run
has already finished (its one interrupt/resume cycle is used), so a
second approve call on a reopened ticket just re-resumes an already-
completed run - reopening surfaces the failure for manual follow-up, it
isn't a retry mechanism.

**Role requirement depends on the ticket's `intent`** (spec §36): all
three routes above (`GET`, `approve`, `reject`) check the caller's role
against `app.config.policies.roles_allowed_to_approve(ticket.intent)`
after fetching the ticket, not before. A `SECURITY`/`FRAUD`/`LEGAL`-intent
ticket requires `SECURITY_AGENT` or `ADMIN` - a `SUPPORT_AGENT` or
`SUPPORT_MANAGER` token gets `403 AUTHORIZATION_ERROR` on all three,
including `GET`. Every other ticket intent accepts
`SUPPORT_AGENT`/`SUPPORT_MANAGER`/`ADMIN`.

## Knowledge base (staff-only, any role unless noted - `Authorization: Bearer <staff JWT>`)

```
GET  /api/v1/knowledge/categories                              -> [{category, article_count}, ...]
GET  /api/v1/knowledge/articles?category=&q=&sort=recent|popular&limit=50  -> [ArticleSummary, ...]
GET  /api/v1/knowledge/articles/{id}                            -> ArticleDetail
GET  /api/v1/knowledge/articles/{id}/related                    -> [ArticleSummary, ...]
GET  /api/v1/knowledge/articles/{id}/file                       -> the original uploaded file (binary)
POST /api/v1/knowledge/articles/{id}/feedback   body: {"helpful": true|false} -> ArticleDetail
POST /api/v1/knowledge/upload   (ADMIN only)   multipart: title, category, file  -> 201 ArticleDetail
POST /api/v1/knowledge/ask   (customer OR staff JWT)   body: {"question": str} -> AskResponse
```

Browse/search/feedback are read-only over the same `knowledge_documents`
table the RAG pipeline retrieves from during a support conversation
(`app.rag.ingest`/`app.rag.docs_ingest`/`app.rag.retriever`). `category` is
free text (whatever `KnowledgeDocument.category` holds), not a fixed enum.

`GET /articles/{id}` increments `view_count` on every call (used to rank
"popular articles"); `POST .../feedback` increments `helpful_yes_count`/
`helpful_no_count` (used for `helpful_percent`, `null` until at least one
vote exists). Both explicitly re-pin `updated_at` to its own value in the
same UPDATE so a mere read/vote never looks like a content edit - the
"recently updated" list sorts by `updated_at`, and TimestampMixin's
`onupdate` would otherwise bump it on every view.

**`POST /upload`** is the one write path in this router - it runs a
manually-uploaded `.md`/`.txt`/`.pdf`/`.docx` file (10MB max) through the
exact same chunk/embed/vector-store pipeline `make seed` and a docs
integration's sync use (`app.rag.ingest.ingest_documents`), so the new
article is retrievable by the AI in the very next customer message, not a
disconnected copy that only shows up in this browse UI. Every upload
creates a new document (its `source` is always a fresh
`upload:<uuid>:<filename>`) rather than trying to detect "is this an
update to an existing article" - that dedupe/version-bump behavior belongs
to automated docs-integration syncs, not a one-off manual upload.
`ArticleDetail.created_by` is set to the uploading admin's staff id -
`null` for anything ingested via `make seed` or a docs-integration sync,
neither of which has a human uploader to attribute.

**Original-file storage** (spec: multi-provider upload storage, R2
default - `app.storage.*`): alongside extracting text, `POST /upload`
makes a best-effort attempt to persist the raw uploaded bytes to whichever
provider `FILE_STORAGE_PROVIDER` selects (`r2`/`s3`/`azure`/`local`,
see docs/ENVIRONMENT.md). This never fails the upload - if the provider
is unconfigured or unreachable, the article is still created with
`has_original_file: false`, since it's already fully usable (browsable,
RAG-retrievable) from `raw_text` alone. When it succeeds,
`GET /articles/{id}/file` streams the original bytes back (`Content-
Disposition: attachment`) - reading from whichever provider that specific
document's file actually lives on, not necessarily the currently-
configured default, since an operator can switch `FILE_STORAGE_PROVIDER`
later without that changing where already-uploaded files are. Run
`scripts/storage/migrate_file_storage.py` (`--dry-run` to preview,
`--delete-old` to remove the source copy once confirmed) to move existing
files onto a newly-selected provider.

Text extraction (`app.rag.file_extractors`) is format-specific: `.md`/`.txt`
are decoded as UTF-8 directly; `.pdf` uses `pypdf` (page-by-page
`extract_text()`, joined - encrypted PDFs and scanned images with no text
layer are rejected with a clear `VALIDATION_ERROR`, not silently ingested
as empty); `.docx` uses `python-docx` (paragraphs, with `Heading N`
styles converted to markdown `#` prefixes, and tables rendered as real
GFM pipe tables - header row, `---` separator, data rows - so structure
survives into the article body as genuine markdown, not flattened text).
The frontend renders `raw_text` as markdown (`ArticleDetail.tsx`); list/
card previews (`summary`) strip the markdown syntax back out first so a
heading or table doesn't show literal `#`/`|` characters in a short
preview. Both libraries are pure-Python - no system
binary like poppler or LibreOffice is required in the Docker image.

**`POST /ask`** is the only route in this router (and one of very few in
the whole API) deliberately open to *either* a customer or a staff token -
`app.security.auth.get_current_user`, a dual-scope dependency that exists
solely for this shared "ask the knowledge base" chat. It retrieves from
the same tenant-scoped vector index `knowledge_search_node` uses during a
real support conversation, then drafts an answer via the same
`draft_response` helper the support workflow itself uses - never a bare,
ungrounded LLM call. Response shape:
`{"answer": str, "grounded": bool, "sources": [{"id", "title", "category"}, ...]}`.
When nothing in the knowledge base is relevant (below the tenant's
retrieval confidence threshold), `grounded` is `false`, `sources` is
empty, and `answer` is a fixed "couldn't find anything" message - never a
hallucinated guess. This route creates no ticket, conversation, or any
other record; it's a stateless, ephemeral lookup, not a replacement for
`POST /api/v1/support/messages` (which still owns tool calls, escalation,
and ticket creation).

## Integrations (JIRA / WooCommerce / email / custom APIs / MCP servers / OpenAPI APIs / docs / Stripe)

```
GET    /api/v1/admin/integrations          (ADMIN only)   -> [Integration, ...]
POST   /api/v1/admin/integrations          (ADMIN only)   body: CreateIntegrationRequest -> 201 Integration
PUT    /api/v1/admin/integrations/{id}     (ADMIN only)   body: UpdateIntegrationRequest -> Integration
DELETE /api/v1/admin/integrations/{id}     (ADMIN only)   -> 204
POST   /api/v1/admin/integrations/{id}/test (ADMIN only)  -> {"ok": bool, "message": "..."}
POST   /api/v1/admin/integrations/{id}/sync (ADMIN only)  -> {"chunks_ingested": int}  (type: "docs" only)
POST   /api/v1/admin/integrations/{id}/rotate-webhook-secret (ADMIN only) -> {"webhook_secret": "..."}
GET    /api/v1/admin/integrations/{id}/oauth/authorize (ADMIN only) -> 307 redirect to the provider's consent screen
GET    /api/v1/oauth/callback/{provider}   -> 307 redirect back to the frontend (no staff JWT - see below)
```

`oauth/authorize`/`oauth/callback` (spec: Phase 10.4, `type: "docs"`
with `auth_type: "oauth2"` only - `provider` is `"google_drive"` or
`"sharepoint"`) are the two-step OAuth2 connection flow: an admin hits
`/oauth/authorize` (staff-authenticated like every other route in this
section) to get redirected to Google/Microsoft's real consent screen
with a signed `state`; after consent, the provider redirects the
browser to `/oauth/callback/{provider}?code=...&state=...` - this route
alone has **no staff JWT dependency at all**, since the caller is the
OAuth provider's own redirect, not an authenticated API call. It's
authenticated instead by verifying the signed `state` (see
docs/SECURITY.md's "OAuth2 docs connectors"); a missing/tampered/expired
state returns `401`, an unknown integration id inside a validly-signed
state also returns `401` (never a distinguishable reason - same
enumeration-prevention posture as the inbound webhooks below). On
success, the exchanged tokens are stored the normal way (`encode_credentials`)
and the browser is redirected to `{first CORS_ALLOWED_ORIGIN}/admin/integrations?connected={id}`.

`rotate-webhook-secret` (spec: Phase 10.1) generates a fresh
`config.webhook_secret` (`secrets.token_hex(32)`) instead of an admin
hand-typing one into `PUT .../{id}`, and returns the real value **exactly
once** in this response - every other integration response (including a
subsequent `GET` of the same integration) masks a truthy
`config.webhook_secret` down to the boolean `true`, the same "reveal
presence, not value" treatment `credential_keys` gives encrypted
credentials. Not restricted to any particular integration `type`.

An `Integration` connects this tenant to an external system - `type` is
one of `jira`/`woocommerce`/`smtp`/`custom`/`mcp`/`openapi`/`docs`/`stripe`,
`auth_type` is `api_key`/`bearer`/`basic`/`none`/`oauth2` (the last one,
spec: Phase 10.4, only for `type: "docs"` with `config.provider:
"google_drive"|"sharepoint"` - see the `oauth/authorize`/`oauth/callback`
routes above; `credentials` is left empty at creation and populated by
the callback instead). `credentials` (e.g.
`{"username": "...", "password": "..."}`) are write-only: sent on
create/update, encrypted at rest, and **never** included in any response
- `GET`/list responses carry `credential_keys` (which fields are set, not
their values) instead. `type: "jira"` requires `config.project_key`;
`type: "mcp"` rejects `auth_type: "basic"` (its Streamable HTTP transport
only sends a header, see docs/SECURITY.md's "External tool calls"
section); `type: "openapi"` requires `config.spec_url` or
`config.spec_inline` (at least one - some real specs aren't published at
a stable URL). For `type: "mcp"`, the `/test` endpoint calls the server's
`tools/list` (discovery itself stays live on every Test - unlike
`openapi`'s spec, nothing re-reads a cached tool list for actual
tool-selection calls) and, as of Phase 10.2, **also persists the result
into `config.discovered_tools`** (`[{"name", "description"}, ...]`, plus
`config.discovered_tools_cached_at`) so the admin UI can show a
"Discovered tools" panel that survives a page reload instead of only a
one-time toast - mirroring `type: "openapi"`'s existing
`config.spec_cache` persistence pattern exactly, with no new route or
response-schema change needed (the existing `/test` route already
commits any mutation `test_connection` makes, for every integration
type). For `type: "openapi"`, it fetches and parses the spec, **caching
the result into `config.spec_cache`** (re-parsing a full OpenAPI
document on every fallback-triggered customer message would be
needlessly slow - the cache is only refreshed by clicking "Test" again)
- both report the discovered tools/operations in `message` instead of a
generic reachability ping. See "DB-backed
runtime settings" and the "External integrations" section in
`docs/SECURITY.md` for the security model, and `docs/DEPLOYMENT.md` for
what each integration actually does.

Two more `config` keys apply only to `type: "mcp"`/`type: "openapi"`
(spec: Phase 7 A2) - both optional, neither changes what `/test`
validates: `config.role: "storefront"` makes this the *primary* path for
commerce questions (order status/cancel/refund/returns/payment
failure/subscription) for the whole tenant, ahead of this app's own
internal orders/payments tables; `config.auto_execute_reads: true`
(only meaningful alongside `role: "storefront"`, only ever applies to a
read-only `GET`/`HEAD` OpenAPI operation) skips the staff-approval ticket
for that one case and answers immediately. See
`docs/ARCHITECTURE.md`'s "Storefront-primary commerce routing" and
`docs/SECURITY.md`'s "External tool calls" for the full behavior.

**`type: "docs"`** (spec: Phase 9.3, Google Drive/SharePoint added in
Phase 10.4) syncs external documents into the knowledge base RAG
retrieval already searches. Requires `config.provider:
"confluence"|"notion"|"google_drive"|"sharepoint"`, plus a
provider-specific "what to sync" key: `config.space_key`/`config.page_ids`
(Confluence), `config.database_id`/`config.page_ids` (Notion),
`config.folder_id`/`config.file_ids` (Google Drive), or `config.drive_id`
(+ optional `config.folder_path`, or `config.file_ids`) (SharePoint) -
at least one required per provider. Optional `config.category` tags
synced documents the same way local knowledge files are categorized
(default `"general"`). Unlike every other integration type's `/test`, a
`"docs"` `/test` call fetches every page's full content (not just a
lightweight reachability check), since every provider client only
exposes a single `fetch_documents()` call - an accepted simplification,
not a bug. `POST .../sync` is the actual ingestion trigger - there is no
scheduler anywhere in this codebase, so nothing runs this automatically;
an admin re-syncs on demand. A page whose version is unchanged since the
last sync is skipped (dedupe); a version bump replaces its chunks rather
than duplicating or silently ignoring the update. Google Drive/SharePoint
use `auth_type: "oauth2"` (see above) instead of a directly-entered
credential - see `docs/ARCHITECTURE.md`'s "RAG doc connectors" for the
full design, including each provider's content-format limitations.

**`type: "stripe"`** (spec: Phase 9.4) is a real Stripe payment gateway -
`auth_type: "bearer"` using the secret key itself
(`credentials.token: "sk_..."`) as the bearer token. Requires
`config.webhook_secret` (Stripe's dashboard-generated signing secret for
the webhook endpoint below - not the API key). `/test` calls `GET
/v1/balance`, Stripe's cheapest key-validity check. Once configured and
enabled, approving a refund ticket whose order has a
`gateway_payment_intent_id` calls Stripe's real refund API instead of
only flipping this app's own `RefundRequest.status`; a tenant with no
`stripe` integration configured keeps today's pure-DB simulation
unchanged. See `docs/ARCHITECTURE.md`'s "Payment gateway (Stripe)" for
the full flow, including why the synchronous API response alone never
marks a refund `"completed"`.

```
POST /api/v1/support/tickets/{id}/jira   (staff, same role check as the ticket itself)
  -> 200 TicketResponse (with external_ref/external_url set)
  -> 400 if no enabled JIRA integration is configured
```

Manually creates a JIRA issue for a ticket that doesn't already have one -
the fallback for when automatic creation (on escalation) was off or
failed. Unlike the automatic path, failures here return a real error
instead of silently no-op'ing.

```
POST /api/v1/support/integrations/woocommerce/lookup   (any staff role)
  body: {"order_number": "1001"}
  -> 200 WooCommerceOrderSummary | null
  -> 400 if no enabled WooCommerce integration is configured
```

Staff-triggered order lookup - not exposed to the AI as an autonomous
tool (see docs/SECURITY.md).

## Webhooks (spec: Phase 8.4, timestamped signature scheme in Phase 10.1)

```
POST /api/v1/webhooks/storefront/{integration_id}
  header: X-Webhook-Signature: t=<unix timestamp>,v1=<hex HMAC-SHA256 of
    "{timestamp}.{raw body}", keyed by the integration's config.webhook_secret>
  body: {"event": "order.shipped", "order_id": "ORD-1001", "data": {...}}
  -> 200 {"received": true, "correlated": bool, "ticket_id": "..."?}
  -> 401 on a missing/wrong/stale (>300s) signature, an unknown
     integration_id, or a disabled integration (all look identical -
     see docs/SECURITY.md)
```

**Breaking change (spec: Phase 10.1)**: this header used to carry a
plain hex HMAC of the raw body with no timestamp - it now shares
Stripe's own `t=...,v1=...` wire format (see the `/webhooks/stripe/{id}`
route below) for real replay protection. The old format is no longer
accepted; `demo_storefront/fire_webhook.py` already signs with the new
scheme.

The **only** route in this API with no staff/customer JWT - the caller is
an external storefront, authenticated by the signature instead.
`correlated: true` means the event matched an existing conversation (via
`Conversation.metadata_json["last_order_id"]`, best-effort, set by
`app.agents.resolution.resolve_via_storefront`) and a new low-priority
`SupportTicket` (`intent: "WEBHOOK"`) was filed on it - `ticket_id` is
only present in that case. `correlated: false` means the event was
received and logged but no matching conversation was found - no ticket
is created (there's no real customer to attach one to). See
`docs/ARCHITECTURE.md`'s "Inbound storefront webhooks" for the full
design, including why this never resumes an existing workflow run.

```
POST /api/v1/webhooks/stripe/{integration_id}   (spec: Phase 9.4)
  header: Stripe-Signature: t=<unix timestamp>,v1=<hex HMAC-SHA256 of
    "{timestamp}.{raw body}", keyed by the integration's config.webhook_secret>
  body: a raw Stripe event object ({"id", "type", "data": {"object": {...}}})
  -> 200 {"received": true, "handled": bool}
  -> 401 on a missing/wrong/stale (>300s) signature, an unknown
     integration_id, or a disabled integration (identical - see docs/SECURITY.md)
```

Also has no staff/customer JWT - authenticated by Stripe's own signature
scheme (genuinely different from the storefront webhook's plain-hex one,
see docs/SECURITY.md's "Inbound Stripe webhooks"). Handles
`payment_intent.succeeded`/`payment_intent.payment_failed` (updates the
matching `Payment.status`) and `refund.updated` (marks the matching
`RefundRequest.status = "completed"` once Stripe reports
`status: "succeeded"`) - any other event type returns
`handled: false` with no action. Configure this exact URL as the webhook
endpoint in the Stripe dashboard for the corresponding `stripe`
integration.

## Errors

Every error is `SupportWorkflowError.to_dict()`:

```json
{"code": "VALIDATION_ERROR", "message": "...", "retryable": false, "severity": "low", "details": {}}
```

`code` is one of `VALIDATION_ERROR | AUTHENTICATION_ERROR |
AUTHORIZATION_ERROR | TOOL_ERROR | LLM_ERROR | RETRIEVAL_ERROR |
POLICY_ERROR | TIMEOUT_ERROR | RATE_LIMIT_ERROR | UNKNOWN_ERROR` (spec §21),
mapped to HTTP 400/401/403/429/422/500 in `app.main`. `POST /support/messages`
and `POST /staff/login` both return `RATE_LIMIT_ERROR` (429) once their
respective limits are exceeded - see `docs/SECURITY.md`.

## Observability

```
GET /metrics   # Prometheus exposition format (app.observability.metrics)
```
