# Deployment

## Local Docker (Postgres + pgvector + Redis)

```bash
make docker-up
```

This builds the API image (`Dockerfile`), starts Postgres (`pgvector/pgvector:pg16`)
and Redis, waits for Postgres's healthcheck, runs `alembic upgrade head`,
then starts `uvicorn`. Switch on real LLM calls by exporting `MOCK_LLM=false`
plus `GOOGLE_API_KEY`/`XAI_API_KEY` (the default provider/fallback pair)
before running it (see `docker-compose.yml`).

Seed it once the containers are up:

```bash
docker compose exec api python scripts/seed/seed_data.py
```

`docker-compose.yml` also starts a `demo_storefront` service (spec:
Phase 8.1) - a tiny, committed FastAPI app standing in for a real
external e-commerce storefront (`demo_storefront/main.py`; no auth, no
persistence, in-memory data reset on every restart). Connect it as this
tenant's primary storefront integration:

```bash
docker compose exec api python scripts/seed/seed_storefront_integration.py
```

This creates an `openapi` integration pointing at
`http://demo_storefront:8000` (the compose-internal DNS name) with
`config.role="storefront"` and `config.auto_execute_reads=true` already
set - click "Test" on it in `/admin/integrations` (or
`POST .../test`) once to cache its operations, then order status/
cancel/refund/exchange/address-change/subscription-plan-change/
payment-retry questions route through it instead of this app's own
internal tables. Override where it's reached with
`STOREFRONT_BASE_URL` (e.g. `http://localhost:8100` for a non-Docker
run against the host-mapped port) before running the seed script.

## Environment variables

See `.env.example` for the full list with defaults. The ones you must
change for a real deployment:

- `JWT_SECRET` - a long random value, from a secrets manager, not
  committed. It signs both customer and staff tokens (distinguished by a
  `scope` claim - see `docs/SECURITY.md`), so rotating it invalidates both.
- `CORS_ALLOWED_ORIGINS` - comma-separated origins the browser frontend
  (`frontend/`) is served from (e.g. `https://support.example.com`). The
  zero-setup default only allows `http://localhost:3000` (`pnpm dev`) -
  a deployed frontend origin not listed here gets its requests blocked by
  the browser, not the API (see `app.main`'s `CORSMiddleware`).
- `DATABASE_URL` - point at your production Postgres.
- `VECTOR_BACKEND=pgvector` - so the knowledge index is durable and shared
  across API instances (the `memory` backend is process-local; see
  `docs/ARCHITECTURE.md`).
- `MOCK_LLM=false` + `GOOGLE_API_KEY` (default provider) + `XAI_API_KEY`
  (default fallback) - see `docs/ARCHITECTURE.md`'s router section for how
  these are resolved. `ANTHROPIC_API_KEY` is also supported if you point
  `DEFAULT_LLM_PROVIDER`/`FALLBACK_LLM_PROVIDER` at `anthropic`.
- `SECURITY_REQUIRE_HUMAN_APPROVAL=true` - keep this true in production.
- `USE_REDIS=true` + `REDIS_URL` - required once you run more than one API
  instance, so rate-limit counters are shared rather than per-instance
  (see `docs/SECURITY.md`). `docker-compose.yml` already sets this for
  you; a non-Docker-Compose deployment must set it explicitly.
- `CHECKPOINT_BACKEND=postgres` - required once you run more than one API
  instance with human-approval flows in active use, so a paused
  refund/external-tool ticket can be resumed by any instance, not just
  the one that paused it (reuses `DATABASE_URL`, no separate connection
  string - see "Production architecture" below).
- `CREDENTIALS_ENCRYPTION_KEY` - a dedicated random value for encrypting
  `Integration.encrypted_credentials`. Optional but strongly
  recommended: without it, this key is derived from `JWT_SECRET`, so
  rotating `JWT_SECRET` also silently breaks every stored integration
  credential (see `docs/SECURITY.md`).
- `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`/`GOOGLE_OAUTH_REDIRECT_URI`
  and `MICROSOFT_OAUTH_CLIENT_ID`/`MICROSOFT_OAUTH_CLIENT_SECRET`/
  `MICROSOFT_OAUTH_TENANT_ID`/`MICROSOFT_OAUTH_REDIRECT_URI` (spec: Phase
  10.4) - only needed for Google Drive / SharePoint docs connectors;
  blank by default. Register an OAuth app in
  [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
  (enable the Drive API, scope `drive.readonly`) or an app registration
  in [Azure AD](https://portal.azure.com) (Microsoft Graph API, scope
  `Files.Read.All` + `offline_access`) - the redirect URI you register
  there **must exactly match** `GOOGLE_OAUTH_REDIRECT_URI`/
  `MICROSOFT_OAUTH_REDIRECT_URI`, which in turn must point at this app's
  own `GET /api/v1/oauth/callback/google_drive` (or `/sharepoint`) route
  on its real public URL.
- **The realtime conversation push (spec: Phase 10.3,
  `app.realtime.connections.ConnectionManager`) is single-instance only**
  - an in-memory `dict[conversation_id, set[WebSocket]]`, same category
  of gap as the default `sqlite` checkpointer and the `memory` vector
  backend above. Running more than one API instance means a customer's
  websocket connection lands on one specific instance, and a storefront
  webhook handled by a *different* instance can't push to it - the
  `SupportTicket` the webhook creates is still correct and visible to
  staff regardless, this only affects the best-effort live nudge. A
  Redis pub/sub-backed variant is a natural fast-follow (this app
  already depends on Redis via `USE_REDIS`) but wasn't built in this
  pass - not required for `docker-compose.yml`'s single-`api`-instance
  setup, but worth knowing before scaling out.
- Create real staff accounts (`staff_users`, via `app.security.passwords.hash_password`)
  instead of relying on the dev seed's `agent_jane` account.
- `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` - optional but recommended
  in production for full request tracing/evaluation (spec §13-15). Once
  set, `python scripts/evaluation/upload_langsmith_datasets.py` uploads
  the labeled eval datasets - see `docs/EVALUATION.md`.
- `LLM_BUDGET_USD_PER_RUN` - optional (unset = unlimited). Caps estimated
  LLM spend per workflow run (spec §42); once a run's `model_requests`
  total would exceed it, the next LLM-calling node short-circuits to an
  escalation (`requires_human=True`) instead of making the call. Token
  usage and per-call cost are recorded in the `model_requests` table
  regardless of whether a budget is set - see "Cost tracking" in
  `docs/ARCHITECTURE.md`.

## Tuning settings without a redeploy (spec §32/§43)

`mock_llm`, `default_llm_provider`/`fallback_llm_provider`, the confidence
thresholds, rate limits, and `LLM_BUDGET_USD_PER_RUN` can all be
overridden per tenant at runtime via `GET/PUT/DELETE
/api/v1/admin/settings` instead of an env var change + redeploy (see
`docs/API.md`). Prefer this over an env var change for anything
tenant-specific or that needs to take effect immediately (e.g. dropping a
misbehaving tenant's budget to $0 while you investigate); keep using env
vars for anything that should be the same across all tenants and set once
at deploy time. Only `ADMIN` role can call this API, and it can never
touch secrets - see "DB-backed runtime settings" in `docs/SECURITY.md`.

## Original-file storage for KB uploads (R2 / S3 / Azure / local)

`FILE_STORAGE_PROVIDER` picks exactly one active provider for storing the
original file behind a Knowledge Base upload - see docs/ENVIRONMENT.md's
"Original-file storage for KB uploads" section for the full variable
list per provider. Defaults to `r2` (Cloudflare R2); an unconfigured or
unreachable provider never breaks an upload, it just leaves that
article's `has_original_file` false.

**Switching providers** (e.g. moving from R2 to S3) does not move
already-uploaded files by itself - each document remembers which
provider its own file actually lives on. Run this once you've updated
`FILE_STORAGE_PROVIDER` (and that provider's credentials) to the new
target:

```bash
python scripts/storage/migrate_file_storage.py --dry-run   # preview first
python scripts/storage/migrate_file_storage.py              # then actually copy
python scripts/storage/migrate_file_storage.py --delete-old  # optional: remove the old copies once confirmed
```

It downloads each document's file from whatever provider it's currently
on and re-uploads it to the newly-configured one, updating the database
row only after the copy succeeds - a failed migration for one document
never loses that file (the old copy stays put unless `--delete-old` is
passed and the new copy already landed).

## External integrations (JIRA / WooCommerce / email / custom APIs / MCP servers / OpenAPI APIs / Stripe)

Connect these from the running app instead of an env var - `ADMIN` ->
Integrations in the frontend, or `POST /api/v1/admin/integrations` (see
`docs/API.md`, `docs/SECURITY.md`'s "External integrations"). No
per-integration env vars exist; everything is per-tenant, encrypted DB
state, editable without a redeploy.

- **JIRA** (`type: "jira"`, `auth_type: "basic"`): base URL is your JIRA
  Cloud site (`https://yourteam.atlassian.net`); credentials are your
  bot account's email + an API token (create one at
  [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens));
  `config.project_key` is required (the project issues get filed under).
  Once connected and enabled, every newly-escalated ticket auto-creates a
  JIRA issue, and approve/reject posts a comment to it.
- **Email** (`type: "smtp"`, `auth_type: "basic"`): base URL is your SMTP
  host (e.g. `smtp.sendgrid.net`, `smtp.gmail.com` with an app password);
  `config.smtp_port` (default 587) and `config.from_email` matter,
  `config.use_tls` defaults to true. Once connected, approving/rejecting
  a ticket emails the customer.
- **WooCommerce** (`type: "woocommerce"`, `auth_type: "basic"`): base URL
  is your store; credentials are a REST API key's consumer key/secret
  (WooCommerce -> Settings -> Advanced -> REST API in wp-admin). Once
  connected, staff can look up an order by number from any ticket.
- **Custom API**: any other REST API - pick `api_key`/`bearer`/`basic`
  to match how it authenticates. Stored the same way; nothing calls it
  automatically yet (see docs/SECURITY.md for why WooCommerce and custom
  connectors aren't wired into the AI's autonomous tool loop).
- **MCP Server** (`type: "mcp"`, `auth_type: "api_key"`, `"bearer"`, or
  `"none"`): base URL is the server's Streamable HTTP endpoint (e.g.
  `https://mcp.example.com/mcp`) - stdio MCP servers aren't supported,
  see docs/SECURITY.md's "External tool calls". `auth_type: "none"`
  matters for genuinely public servers that reject a request carrying any
  Authorization header at all, even an unused one (live-verified against
  `mcp.deepwiki.com`).
- **OpenAPI / Swagger** (`type: "openapi"`, any auth type): base URL is
  the API's actual reachable base (e.g. `https://api.example.com`) -
  separate from where the spec itself comes from; `config.spec_url` (a
  URL to fetch) or `config.spec_inline` (a pasted spec, for APIs whose
  spec isn't published at a stable URL) is required, at least one of the
  two. Click "Test" after connecting to parse the spec and cache its
  operations into `config.spec_cache` - unlike MCP's always-live
  discovery, this cache is only refreshed by clicking "Test" again, not
  on every customer message.
- **Confluence / Notion docs** (`type: "docs"`, spec: Phase 9.3): syncs
  external pages into the same knowledge base RAG retrieval already
  searches. `config.provider: "confluence"` (`auth_type: "basic"` - a
  Confluence Cloud bot account's email + API token, same credential
  shape as this integration's JIRA connector) or `config.provider:
  "notion"` (`auth_type: "bearer"` - an internal integration token from
  [notion.so/my-integrations](https://www.notion.so/my-integrations); the
  admin must also explicitly share the relevant pages/database with that
  integration inside Notion's own UI first, or the API sees nothing).
  `config.space_key` (Confluence) / `config.database_id` (Notion) syncs
  everything in that space/database, or use `config.page_ids` for an
  explicit list - at least one is required. Optional `config.category`
  tags synced content (default `"general"`). Click "Test" to verify the
  connection (fetches real content, not just a reachability ping - see
  docs/API.md), then `POST /admin/integrations/{id}/sync` to actually
  ingest - there is no scheduler anywhere in this codebase, so re-sync
  whenever the source content changes. **No real Confluence/Notion
  workspace has been connected in this project's own testing yet** -
  built and verified against a fixture server implementing the real
  Confluence Cloud v2 API shape (docs/ARCHITECTURE.md's "RAG doc
  connectors" has the full live-verification note); connecting a genuine
  workspace is the natural next step, not expected to need any code
  changes to work.
- **Stripe** (`type: "stripe"`, `auth_type: "bearer"`, spec: Phase 9.4):
  base URL `https://api.stripe.com`; `credentials.token` is your secret
  key (`sk_test_...`/`sk_live_...` - it doubles as the bearer token,
  Stripe has no separate concept); `config.webhook_secret` is required
  (the signing secret Stripe generates when you add the webhook endpoint
  below - a different value from the API key). Click "Test" to check
  `GET /v1/balance`. Once connected and enabled, approving a refund
  ticket whose order has a `gateway_payment_intent_id` calls Stripe's
  real refund API instead of only updating this app's own DB row; a
  tenant with no `stripe` integration keeps today's pure-DB simulation.
  In the Stripe dashboard, add a webhook endpoint pointing at
  `https://<your-domain>/api/v1/webhooks/stripe/{integration_id}`,
  subscribed to at least `payment_intent.succeeded`,
  `payment_intent.payment_failed`, and `refund.updated` - see
  docs/API.md's "Webhooks" and docs/SECURITY.md's "Inbound Stripe
  webhooks". **No real Stripe account or test-mode keys exist in this
  project's own testing yet** - built and verified against
  respx-mocked HTTP shaped to match Stripe's real, public API
  documentation, plus one live round trip against the real
  `api.stripe.com` with a deliberately fake key (confirming the real
  auth-header construction up to Stripe's own 401 boundary). Connecting
  a real test-mode account and exercising one real refund end to end is
  the natural next step, not expected to need any code changes.
- **Google Drive / SharePoint docs** (`type: "docs"`, `auth_type: "oauth2"`,
  spec: Phase 10.4): unlike every other integration type, credentials
  aren't entered directly - create the integration with `config.provider:
  "google_drive"` (+ `config.folder_id` or `config.file_ids`) or
  `"sharepoint"` (+ `config.drive_id`, optional `config.folder_path`, or
  `config.file_ids`) and no `credentials`, then click "Connect" (or
  `GET /admin/integrations/{id}/oauth/authorize`) to go through a real
  OAuth2 consent screen - the callback stores the resulting tokens
  automatically. Requires registering an app first (see the env vars
  below); only Google Docs (Drive) and `.txt`/`.md` files (SharePoint)
  are fetched as content - other formats are a documented v1 limitation,
  not a bug (see docs/ARCHITECTURE.md's "RAG doc connectors"). **No real
  Google Cloud OAuth app or Azure AD app registration exists in this
  project's own testing yet** - built and verified against respx-mocked
  token/content endpoints, plus one live round trip against the real
  `oauth2.googleapis.com/token` with a blank client id (confirming the
  real request reaches Google's token endpoint and its real error
  response is correctly parsed, the same "hit the real API boundary
  without full credentials" shape already used for Stripe). Registering
  a real app and exercising one real sync end to end is the natural next
  step, not expected to need any code changes.

For both MCP and OpenAPI: once connected and enabled, the discovered
tools/operations become available to the agent as a bounded fallback
(only when no built-in resolver or knowledge-base match applies), and
every proposed call requires staff approval on the resulting ticket
before it actually runs - regardless of source or HTTP method, it is
never auto-executed like WooCommerce lookup.

**Connecting a real external storefront** (spec: Phase 7 A2): check "Use
as the primary storefront for order/refund/subscription questions" when
connecting an `mcp`/`openapi` integration (sets `config.role:
"storefront"`) to make it the *primary* path for commerce questions for
this tenant, ahead of this app's own internal orders/payments tables -
not just the bounded fallback above. Only one such integration is
consulted per tenant. Also checking "Auto-answer read-only lookups
without a staff approval ticket" (`config.auto_execute_reads: true`,
`openapi` only) lets a read-only (`GET`/`HEAD`) operation - e.g. "where's
my order" - answer immediately with no approval ticket; a mutating
operation (cancel, refund, ...) always still requires staff approval
regardless of this setting. See docs/ARCHITECTURE.md's "Storefront-primary
commerce routing" and docs/SECURITY.md's "External tool calls" for the
full behavior and threat model.

Use "Test" in the Integrations screen (or `POST .../test`) after
connecting - it makes a real lightweight call (JIRA: `/rest/api/2/myself`,
WooCommerce: list one order, SMTP: connect+login, MCP: `tools/list`,
OpenAPI: fetch+parse the spec, and the response names what it found) so a
bad URL or expired token is caught immediately instead of on the first
real escalation.

### Manual webhook demo (spec: Phase 8.4, timestamped signature in Phase 10.1)

To receive inbound events from a connected storefront, set
`config.webhook_secret` on its `mcp`/`openapi` integration - either pick
a value yourself and resend the rest of the existing `config` alongside
it via `PUT /admin/integrations/{id}` (which replaces `config` wholesale,
not merges it), or generate one with `POST /admin/integrations/{id}/rotate-webhook-secret`
(spec: Phase 10.1 - returns the real value once). Then have the
storefront `POST` to `/api/v1/webhooks/storefront/{integration_id}` with
an `X-Webhook-Signature` header of the form
`t=<unix timestamp>,v1=<hex HMAC-SHA256 of "{timestamp}.{raw body}">`,
keyed by that secret (a breaking change from the original Phase 8.4
scheme - see `docs/API.md`'s "Webhooks" for the envelope shape).

`demo_storefront/fire_webhook.py` (spec: Phase 8.1) sends a real signed
request for manual testing against a real running instance of this app:

```bash
python -m demo_storefront.fire_webhook \
  --base-url http://localhost:8000 \
  --integration-id <the connected integration's id> \
  --secret <its config.webhook_secret> \
  --event order.shipped --order-id ORD-1001
```

Only creates a visible `SupportTicket` if `order_id` matches an existing
conversation's `Conversation.metadata_json["last_order_id"]` (set
opportunistically whenever the AI successfully proposes/executes a
storefront call about that order - see docs/ARCHITECTURE.md's "Inbound
storefront webhooks"); otherwise the event is acknowledged and logged,
not force-fit into a ticket with no real customer to attach it to.

## Multi-tenant deployment (spec §43)

Every table carries a `tenant_id` (default `"default"`), and every
customer/staff JWT carries a `tenant_id` claim that all data access is
scoped by - see "Multi-tenancy & tenant isolation" in `docs/SECURITY.md`.
This build ships a **shared-schema, single-database** multi-tenancy
model: all tenants live in the same Postgres database and vector store,
isolated by a `tenant_id` column/namespace rather than separate databases
or schemas per tenant. Notes for running more than the default tenant:

- Creating a new tenant is just minting tokens with a new `tenant_id` -
  there is no separate tenant-provisioning table or endpoint; a
  `staff_users` row's `tenant_id` (set at creation, e.g. via
  `POST /api/v1/staff/users`) determines which tenant its issued tokens
  carry.
- The vector store namespace is derived from `tenant_id`
  (`app.rag.ingest.knowledge_namespace`), so knowledge documents must be
  ingested per tenant (`ingest_knowledge_directory(..., tenant_id=...)`);
  there is no cross-tenant knowledge base by default.
- This shared-schema model does not by itself satisfy strict regulatory
  data-residency/isolation requirements (e.g. a tenant contractually
  requiring a physically separate database) - if that's a requirement,
  plan for a database-per-tenant deployment instead, which this build's
  repository layer doesn't currently support.

## Production architecture

```
                  Load Balancer
                       |
              +--------+--------+
              |                 |
          API Instance      API Instance   (stateless FastAPI/uvicorn)
              |                 |
              +--------+--------+
                       |
          +------------+------------+
          |            |            |
       Postgres    pgvector      Redis        (idempotency/rate-limit cache)
       (+ pgvector  (same DB,
        extension    separate
        or table)    table)
```

Multiple API instances are safe to run behind a load balancer **except**
for the LangGraph checkpointer: this build's default `AsyncSqliteSaver`
writes to a local file (`CHECKPOINT_DB_PATH`), which is fine for a single
instance but not shared across instances. Set `CHECKPOINT_BACKEND=postgres`
(spec: Phase 9.1a) before scaling the API horizontally with
human-approval flows in active use, so a paused run can be resumed by
*any* instance, not just the one that started it - this reuses
`DATABASE_URL` rather than a separate connection string, and needs no
other configuration. The schema (`checkpoints`/`checkpoint_writes`/
`checkpoint_blobs`/`checkpoint_migrations` tables, alongside - not part
of - the Alembic-managed tables) is initialized once by
`python -m app.scripts.setup_checkpointer`, which `docker-compose.yml`'s
`api` command already runs on every boot, immediately after `alembic
upgrade head` - it's a no-op (exit 0, nothing to do) whenever
`CHECKPOINT_BACKEND` isn't `"postgres"`, so it's always safe to leave in
the startup command regardless of backend. Live-verified against this
project's own real Postgres service: a full pause-on-approval / resume
round trip (a real refund ticket approved via `POST /tickets/{id}/approve`)
with `CHECKPOINT_BACKEND=postgres` correctly read and wrote checkpoint
rows in Postgres, not the local sqlite file.

Redis-backed rate limiting (`app.security.rate_limit.RedisRateLimiter`)
is already fully implemented and already the default in
`docker-compose.yml` (`USE_REDIS=true`) - no code change was needed
here. The one actionable gap: **any production deployment that doesn't
use this project's `docker-compose.yml`** (bare-metal, ECS/Kubernetes,
etc.) must set `USE_REDIS=true` itself, or every instance silently falls
back to independent in-memory counters with no error or warning,
multiplying the effective rate limit by instance count.

## Database migrations

Production deployments must use Alembic, not `init_models()` (which only
runs for the SQLite dev path - see `app.main`'s `lifespan`):

```bash
alembic upgrade head
```

`docker-compose.yml`'s `api` service runs this automatically on boot.
Never rely on auto-created schemas in production (spec §27).

**SQLite now enforces foreign keys too** (`app.db.session.get_engine`
issues `PRAGMA foreign_keys=ON` on every SQLite connection), specifically
so this class of bug can't hide in the zero-setup dev path: several
`ForeignKey` columns in this codebase are plain columns, not ORM
`relationship()`s, so SQLAlchemy's unit-of-work has no dependency graph to
sort flush order by - a child row queued before its parent's INSERT has
actually run would previously insert successfully on SQLite (which never
enforced the constraint) and only fail against Postgres (which always
does). This was a real, live bug caught by first running this build
against Postgres in this session (fixed in `app.rag.ingest` and
`app.workflow.runner` - the latter could have broken every brand-new
conversation's first message in a Postgres deployment). If you add a new
`ForeignKey` column, either flush the parent object before adding the
child, or add a proper `relationship()` so SQLAlchemy orders it for you -
and you'll find out immediately in the test suite now, not after
deploying to Postgres.

## Health checks

- `GET /api/v1/health` - liveness (no dependencies checked).
- `GET /api/v1/ready` - readiness (checks DB connectivity via `SELECT 1`).
- The `Dockerfile`'s `HEALTHCHECK` hits `/api/v1/health`.

## Rolling out a prompt/model change

1. Run `make evaluate` locally against the new provider/model (set
   `MOCK_LLM=false` and the relevant `*_API_KEY`/`*_MODEL` vars).
2. CI (`.github/workflows/ci.yml`) re-runs it - a regression below the
   thresholds in `docs/EVALUATION.md` fails the build.
3. Deploy behind a feature flag or canary if the change is significant;
   `app.llm.router.get_llm_router()` resolves provider/model from
   `Settings` on every call (via `get_settings()`), so a config-only
   rollout (e.g. changing `GOOGLE_MODEL`) doesn't need a code change.

## Load testing

```bash
pip install locust  # already in the dev extras
make seed
RATE_LIMIT_ENABLED=false make dev &   # the per-customer rate limit would otherwise dominate the results
LOAD_TEST_TOKEN=<token from make seed> locust -f tests/load/locustfile.py --host http://localhost:8000
```

Sweep `--users`/`--spawn-rate` for the 10/50/100/500 RPS targets from spec
§36 and read p50/p95/p99 latency and error rate from Locust's own report.
Note the zero-setup defaults (SQLite, in-memory vector store, mock LLM)
are not representative of production load characteristics - point
`DATABASE_URL`/`VECTOR_BACKEND` at the real Postgres/pgvector stack before
drawing conclusions from a load test.
