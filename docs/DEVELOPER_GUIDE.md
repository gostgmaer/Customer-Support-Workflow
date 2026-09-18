# Developer Guide

Onboarding for engineers working on this codebase. This is the map; for
deep dives follow the pointers to `docs/ARCHITECTURE.md` (system design),
`docs/API.md` (HTTP contract), `docs/SECURITY.md` (threat model),
`docs/DEPLOYMENT.md` (running it for real), `docs/EVALUATION.md`
(intent/retrieval eval datasets), and `docs/TROUBLESHOOTING.md` (common
gotchas) rather than duplicating them here.

## What this is, in one paragraph

An AI customer support platform **for e-commerce**, built as a FastAPI +
LangGraph + LangChain backend running a multi-node agent workflow
(classify intent -> retrieve knowledge -> resolve via a deterministic
tool or a connected storefront -> apply a safety/grounding review ->
optionally pause for human approval -> respond), with a Next.js frontend
covering customer chat, a staff ticket queue, and an admin console. The
core scenarios are order lifecycle ones - status, cancel, refund, return,
payment retry, subscription change - resolvable against this app's own
order data or, once an OpenAPI/MCP integration is tagged as the
storefront, a real external one; JIRA/email/custom-API integrations and
generic RAG doc connectors (Confluence/Notion/Drive/SharePoint) exist as
supporting infrastructure around that core. Multi-tenant, RBAC'd,
cost-tracked, and built to run with zero external services out of the box
(SQLite + an in-memory vector store + a deterministic mock LLM) while
supporting real Postgres/pgvector/Redis/real LLM providers as opt-in
production backends.

## Repository layout

```
app/                    FastAPI backend
  agents/               classification, resolution, external-tool selection, confirmation
  api/routes/           HTTP routes (one module per resource)
  api/schemas/          Pydantic request/response models
  config/               Settings, policies (permission matrices), dynamic per-tenant settings
  db/                   Session/engine setup, base model mixins
  domain/               ORM models, enums (Intent, StaffRole), structured exceptions
  integrations/         Outbound clients per external system (JIRA, Stripe, MCP, OpenAPI, docs, etc.)
  llm/                  Provider router + adapters (Google/xAI/Anthropic/Mock), pricing
  observability/        Structured logging, metrics, tracing, retry policy
  rag/                  Ingestion, embeddings, retrieval, reranking
  realtime/             In-process websocket connection registry
  repositories/         Tenant-scoped DB query layer, one per aggregate
  security/             Auth (JWT), passwords, rate limiting, webhooks, OAuth2, authorization
  tools/                The AI's actual callable tools (orders, refunds, payments, subscriptions, customer)
  workflow/             The LangGraph graph itself: nodes, state, runner, routers
frontend/               Next.js app (customer chat, staff queue, admin console)
demo_storefront/        A second, tiny FastAPI app - a realistic external storefront fixture
migrations/             Alembic migrations
scripts/                Seed data, evaluation runner, one-off setup scripts
tests/                  unit / integration / workflow / security / evaluation
docs/                   Everything referenced above
```

## Local setup

```bash
make install            # pip install -e ".[dev]"
make seed               # seed data.db with demo customers/staff/orders
make dev                # uvicorn --reload on :8000
cd frontend && pnpm install && pnpm dev   # Next.js on :3000
```

Zero-setup defaults: SQLite (`./data/support.db`), `VECTOR_BACKEND=memory`,
`MOCK_LLM=true` (a deterministic keyword-matching provider - no API key
needed, and what the test suite runs against). Flip real backends on via
env vars - see `docs/DEPLOYMENT.md` for the full list and what each one
unlocks. `docker compose up --build` (`make docker-up`) runs the full
stack instead (Postgres+pgvector, Redis, the API, and the demo storefront
fixture).

## Architecture at a glance

The workflow is a LangGraph graph (`app/workflow/graph.py`), one node per
step, `app/workflow/runner.py` drives a run and owns the checkpointer
(SQLite by default, Postgres for multi-instance - `CHECKPOINT_BACKEND`).
Roughly:

```
classify (intent) -> route_request -> [resolve via a deterministic tool
  OR retrieve from the knowledge base OR propose an external-tool/storefront
  call] -> policy/grounding/review safety checks -> human_approval_gate
  (interrupts here if approval is needed) -> save_outcome
```

- **Tools** (`app/tools/`) are the AI's only way to touch real data - each
  one is gated by `app.config.policies.TOOL_PERMISSION_MATRIX`
  (`ToolPolicy(requires_customer_confirmation, human_approval_level, ...)`)
  - never trust a tool call without checking this matrix first when adding
    one.
- **Resolution** (`app/agents/resolution.py`) maps an intent to either an
  internal tool (`INTENT_RESOLVERS`) or, for commerce intents
  (`COMMERCE_INTENTS`), a connected storefront integration if one exists
  and is tagged `role: "storefront"` - internal tools stay the default,
  unaffected fallback for any tenant without one.
- **External tools** (`app/agents/external_tools.py`) unify MCP servers and
  OpenAPI-described APIs into one numbered-menu selection the LLM narrows,
  never a free-form tool-calling loop - every proposal (from either
  source) needs human approval by default.
- **RAG** (`app/rag/`) uses a pluggable `Embedder`/`VectorRepository` -
  `HashingEmbedder`/`InMemoryVectorStore` need nothing to run; a real
  embeddings model + pgvector are opt-in. External doc sources
  (Confluence/Notion/Drive/SharePoint) sync into the exact same pipeline
  local markdown files use.
- **Safety pipeline**: policy checks, a grounding check (is every claim
  backed by a retrieved document or tool result), and a response-quality
  review all run before a response reaches the customer - see
  `docs/ARCHITECTURE.md` for the full node-by-node breakdown.
- **Multi-tenancy**: every table has `tenant_id`
  (`TenantScopedMixin`/`TenantScopedRepository`); every JWT carries a
  `tenant_id` claim; the zero-setup default tenant is `"default"`.
- **RBAC**: `app.domain.enums.role.StaffRole` +
  `app.config.policies.roles_allowed_to_approve(intent)` - a
  `SECURITY`/`FRAUD`/`LEGAL` ticket is gated to `SECURITY_AGENT`/`ADMIN`
  only, everything else to any staff role.
- **Cost tracking**: every LLM call records a `model_requests` row
  (provider/model/tokens/estimated cost); `LLM_BUDGET_USD_PER_RUN` can cap
  spend per workflow run.

## How to extend the system

### Add a new intent

Six places have historically drifted from each other - treat this as a
literal checklist, in this order:

1. `app/domain/enums/intent.py` - add to `Intent(StrEnum)`, and to
   `DATA_REQUIRED_INTENTS` if it needs customer/order data.
   (`KNOWLEDGE_REQUIRED_INTENTS` in the same file is dead code - don't
   bother updating it.)
2. `app/agents/resolution.py` - `COMMERCE_INTENTS` and/or
   `KNOWLEDGE_INTENTS`, plus `INTENT_RESOLVERS` if there's an internal
   tool for it (skip this if it's storefront-only, like `EXCHANGE`).
3. `app/workflow/routers/route_request.py` - its own, separately
   maintained `MUTATING_INTENTS`/`READ_ONLY_DATA_INTENTS`/`KNOWLEDGE_INTENTS`
   (not imported from `resolution.py` - a second set that must be kept in
   sync manually).
4. `app/agents/confirmation.py` - `CONFIRMATION_CAPABLE_INTENTS`, if a
   customer confirmation round-trip applies (skip for a storefront-only
   intent with no internal resolver).
5. `app/llm/providers/mock.py` - a new `_KEYWORD_INTENTS` regex entry.
   Without this, `MOCK_LLM=true` (the zero-setup default *and* what tests
   run against) never classifies the new intent at all, and nothing else
   signals the omission.
6. `app/config/policies.py` - a `TOOL_PERMISSION_MATRIX` entry for any new
   internal tool the resolver calls - `get_tool_policy` fails closed for
   anything unlisted.

### Add a new tool

Put it in the right `app/tools/*.py` file (or a new one, following the
existing shape: a Pydantic args model, an async function taking
`ToolContext`, wrapped so failures raise `ToolError`). Add its
`TOOL_PERMISSION_MATRIX` entry. Wire it into a resolver in
`app/agents/resolution.py` if an intent should call it automatically.

### Add a new integration type

Look at the most similar existing one first - `app/integrations/jira.py`
(basic auth, simple REST) or `app/integrations/docs_connector.py`
(multiple providers dispatched on `config.provider`) are good templates.
Extend `_TYPE_PATTERN`/`_AUTH_PATTERN` and
`_check_type_specific_requirements` in `app/api/schemas/integration.py`,
add a branch to `app/integrations/health.py`'s `test_connection` for the
admin "Test" button, and use `app.integrations.base.build_http_client`
for the actual HTTP calls rather than constructing your own client - it
already handles every auth type this app supports.

### Add a new LLM provider

Implement the same interface as `app/llm/providers/mock.py` (the
reference/no-key-needed one) or `_langchain_base.py`'s helpers (used by
Google/xAI/Anthropic) - `generate`/`generate_structured`, both accepting
an optional `usage_callback` for cost tracking. Register it in
`app/llm/router.py` and add pricing to `app/llm/pricing.py`.
`tests/unit/test_llm_provider_contract.py` runs the same contract test
against every provider - a new one should pass it unmodified.

### Add a new RAG doc connector

Match `app/integrations/docs_connector.py`'s duck-typed interface:
`__init__(integration, ...)` + `async fetch_documents() ->
list[LoadedDocument]`. Register it in `get_docs_client`. No changes
needed to `app/rag/docs_ingest.py` or the ingestion pipeline itself - it's
provider-agnostic as long as `LoadedDocument.version` reflects when the
source content last changed.

## Testing

```bash
make test        # pytest -q (full suite)
make lint         # ruff check .
make typecheck    # mypy app
make evaluate     # intent/retrieval/tool-selection eval dataset (see docs/EVALUATION.md)
```

- `tests/unit/` - pure logic, heavily mocked (respx for HTTP, a stub LLM
  for classifier/resolution logic).
- `tests/integration/` - full HTTP request/response through the real
  FastAPI app (`httpx.AsyncClient` + `ASGITransport`) against a real
  (SQLite, in-memory) DB - the `client` fixture in `tests/conftest.py`.
- `tests/workflow/` - full end-to-end scenarios through
  `POST /support/messages`, asserting on real DB state after the graph
  runs (`tests/workflow/test_scenarios.py`).
- `tests/security/` - auth, rate limiting, prompt-injection resistance.
- Websocket routes need `starlette.testclient.TestClient.websocket_connect`
  instead of the usual `client` fixture - `httpx.ASGITransport` doesn't
  support the websocket ASGI scope (see `tests/integration/test_support_ws.py`).
- External HTTP calls are mocked with `respx` throughout, matching each
  real provider's actual, public API shape rather than an invented one -
  when adding a new external call, verify the real shape (a public API's
  docs, or a throwaway probe against the real service) before writing the
  fixture.

## Database & migrations

SQLAlchemy async ORM, Alembic for schema changes (`migrations/versions/`).
`make migrate` (`alembic upgrade head`) applies them; the zero-setup
SQLite path also auto-creates tables on startup for convenience
(`app.db.session.init_models`, dev/test only - production always uses
migrations). New tables must inherit `TenantScopedMixin` and get a
`TenantScopedRepository` subclass, matching every existing repository in
`app/repositories/`.

## Conventions worth knowing before your first PR

- Structured errors only (`app.domain.exceptions.SupportWorkflowError`
  subclasses) - never raise a bare `Exception` across a route/tool
  boundary; `app/main.py`'s exception handler maps each error's `code` to
  an HTTP status.
- Every integration's outbound credentials go through
  `app.integrations.base.encode_credentials`/`get_credentials` (Fernet
  encryption) - never store a secret in `Integration.config` in plaintext
  except a value explicitly designed to be regenerable and one-time-shown
  (e.g. `webhook_secret`, masked to a boolean on every other response).
- No scheduler/cron exists anywhere in this codebase - anything that looks
  like it needs periodic execution (doc sync, etc.) is a manual,
  admin-triggered action today, by design.
- This app runs correctly with zero external services - don't add a
  feature that hard-requires Postgres/Redis/a real LLM key without an
  equivalent zero-setup fallback, matching every existing subsystem's
  precedent (checkpointer, vector store, rate limiter).
