# Customer Support Workflow

A production-grade AI customer support platform for e-commerce, built on
**FastAPI**, **LangGraph**, and **LangChain**: an AI agent that handles the
real order lifecycle - status, shipping, cancellations, refunds, returns,
payment retries, subscription changes - either against this app's own data
or a real connected storefront, backed by RAG over a versioned knowledge
base, a policy/grounding/response-review safety pipeline, human-in-the-loop
approval for high-risk actions, full observability/audit trail,
multi-tenancy, six-role RBAC, and per-run LLM cost tracking with budget
enforcement. JIRA/email/custom-API/MCP integrations and generic doc sync
(Confluence/Notion/Drive/SharePoint) are supporting infrastructure around
that core, not the product's focus.

New here? Start with `docs/USER_GUIDE.md` (using the running app as a
customer/staff member/admin) or `docs/DEVELOPER_GUIDE.md` (codebase tour,
local setup, how to extend it). See `docs/ENVIRONMENT.md` for every env
var this app reads and what it's for. For deep dives: `docs/ARCHITECTURE.md`
for the design, `docs/API.md` for the HTTP API, `docs/SECURITY.md` for the
security model, `docs/EVALUATION.md` for the evaluation harness,
`docs/DEPLOYMENT.md` for production deployment, and
`docs/TROUBLESHOOTING.md` for common gotchas.

## Quick start (zero setup)

Requires Python 3.12+. No Docker, no API keys, no database server needed -
the default configuration uses SQLite, an in-memory vector store, and a
deterministic mock LLM provider.

```bash
make install     # pip install -e ".[dev]"
make seed        # seeds customers/orders/payments/subscriptions + knowledge base
make dev         # starts the API on http://localhost:8000
```

`make seed` prints a bearer token for each seeded customer. Use one to call the API:

```bash
curl -X POST http://localhost:8000/api/v1/support/messages \
  -H "Authorization: Bearer <token-from-make-seed>" \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"conv_1","message_id":"m1","message":"Where is my order?","channel":"web"}'
```

`make seed` also creates one staff login per RBAC role (`agent_jane`/
`SUPPORT_AGENT`, `manager_mo`/`SUPPORT_MANAGER`, `admin_priya`/`ADMIN`,
`security_sam`/`SECURITY_AGENT`, all password `dev-agent-password`) - log
in via `POST /api/v1/staff/login` to get a token that can approve/reject
the refund tickets a conversation produces (see `docs/API.md`). Which
role a given ticket requires depends on its intent - security/fraud/legal
tickets need `SECURITY_AGENT`/`ADMIN`, everything else accepts
`SUPPORT_AGENT`/`SUPPORT_MANAGER`/`ADMIN` (see `docs/SECURITY.md`).

Try the other sample scenarios from `docs/API.md` / spec §43 - refund
(multi-turn confirmation + human approval), a security report (always
escalates), and an out-of-scope question (never hallucinates, escalates
instead).

Run the tests:

```bash
make test        # unit + integration + workflow + security tests
make evaluate    # intent/priority/escalation accuracy against tests/evaluation/dataset.py
make lint        # ruff
make typecheck   # mypy
```

## Going to "real" providers

Everything behind an external dependency has a working local/mock
implementation by default, and a real implementation you opt into via
environment variables (see `.env.example`):

| Concern       | Zero-setup default              | Production option                          |
| ------------- | -------------------------------- | ------------------------------------------- |
| LLM           | `MOCK_LLM=true` (deterministic, offline) | `MOCK_LLM=false` + `GOOGLE_API_KEY`/`XAI_API_KEY` (default primary/fallback - see below) |
| Embeddings    | `HashingEmbedder` (lexical, deterministic - automatic whenever `MOCK_LLM=true` or no `GOOGLE_API_KEY`) | Real `gemini-embedding-2` via LangChain, automatic once `MOCK_LLM=false` + `GOOGLE_API_KEY` are set |
| Database      | SQLite (`DATABASE_URL=sqlite+aiosqlite:///...`) | Postgres (`DATABASE_URL=postgresql+asyncpg://...`) |
| Vector store  | `VECTOR_BACKEND=memory` (process-local numpy) | `VECTOR_BACKEND=pgvector` (real `vector` column + HNSW index, plus `tsvector`/GIN full-text for hybrid retrieval) |
| Checkpointer  | SQLite (`CHECKPOINT_DB_PATH`)    | Swap for `langgraph-checkpoint-postgres` in a multi-instance deployment |

None of `app/workflow`, `app/agents`, or `app/api` change when you swap any
of these - they depend only on the interfaces in `app/llm/`,
`app/repositories/vector_store.py`, and SQLAlchemy's async engine.

### LLM providers: Gemini default, Grok fallback, provider-agnostic

`app/llm/router.py` is the only thing the rest of the app talks to -
callers ask for a model **by purpose** (e.g. `get_llm_router().get_model("intent_classification")`),
never by vendor. With `MOCK_LLM=false`:

- `DEFAULT_LLM_PROVIDER=google` (Gemini, via `langchain-google-genai`) serves
  every purpose unless overridden per-profile in `app/llm/profiles.py`.
- `DEFAULT_LLM_PROVIDER=xai` (Grok, via `langchain-xai`) is the fallback -
  the router retries the primary, then fails over automatically, tracking
  provider health (`app/llm/health.py`) so a provider that keeps failing is
  skipped rather than retried every time.
- Anthropic Claude is also available (`DEFAULT_LLM_PROVIDER=anthropic` /
  `FALLBACK_LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY`).
- Adding OpenAI/Azure/Bedrock/Ollama/OpenRouter/etc: one ~15-line file in
  `app/llm/providers/` following `google.py`/`xai.py` (each just wraps a
  LangChain `BaseChatModel`), registered in `app/llm/factory.py` - see
  `docs/ARCHITECTURE.md`.

Set `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY` to get full LangSmith
tracing across every LLM call, tool call, and retrieval step for free (spec
§13-15) - no code changes needed, LangChain/LangGraph auto-trace once those
env vars are set. Run `python scripts/evaluation/upload_langsmith_datasets.py`
once the key is set to upload the labeled eval datasets (see
`docs/EVALUATION.md`).

Every LLM call is recorded to a `model_requests` table (provider, model,
token counts, estimated cost, which node/workflow-run it came from) via
`app.llm.router.RecordingLLMRouter` - no changes needed at any of the
existing call sites. Set `LLM_BUDGET_USD_PER_RUN` to cap estimated spend
per workflow run; once exceeded, further LLM-calling nodes in that run
escalate to a human instead of making the call (spec §42).

A handful of operational settings - `mock_llm`, provider selection,
confidence thresholds, rate limits, the LLM budget - can also be
overridden per tenant at runtime via `GET/PUT/DELETE
/api/v1/admin/settings` (`ADMIN`-only) instead of an env var + redeploy.
Secrets are never part of this - see "DB-backed runtime settings" in
`docs/SECURITY.md`.

### Multi-tenancy & RBAC

Every table carries a `tenant_id` (default `"default"` - no config needed
for a single-tenant deployment), enforced at the JWT-claim, repository-
query, and vector-namespace layers independently (spec §43). Staff
accounts have one of four roles (`SUPPORT_AGENT`, `SUPPORT_MANAGER`,
`ADMIN`, `SECURITY_AGENT`) plus a separate `SYSTEM` token scope for
service-to-service calls (spec §36); `POST /api/v1/staff/users`
(`ADMIN`-only) creates new staff accounts with any role. See
"Multi-tenancy & tenant isolation" and "RBAC" in `docs/SECURITY.md`.

### External integrations

Connect JIRA, email (SMTP), WooCommerce, an MCP (Model Context Protocol)
server, an OpenAPI/Swagger-described REST API (e.g. an external
storefront), Confluence, Notion, Google Drive, or SharePoint (for RAG -
see below), Stripe (a real payment gateway - see below), or any other
REST API from `ADMIN` -> Integrations (or `POST /api/v1/admin/integrations`)
- no env vars, no redeploy. Once connected: escalated tickets
auto-create a JIRA issue and get commented on approve/reject,
approve/reject can email the customer, staff can look up a WooCommerce
order from any ticket, and the agent can propose calling a connected MCP
server's tools or OpenAPI operations (merged into one menu) as a
fallback when nothing else applies - every proposal needs staff approval
before it actually runs, the same as a refund. Tagging an MCP/OpenAPI
integration `role: "storefront"` instead makes it the *primary* path for
order/refund/subscription questions for that tenant, ahead of this app's
own internal tables - so the AI can run the full order lifecycle against
a real external storefront; a per-integration `auto_execute_reads`
opt-in lets read-only lookups answer immediately without a ticket, while
every mutating action still always needs approval. Credentials are
encrypted at rest and never returned by the API. A connected storefront
can also push events back - a signed
`POST /api/v1/webhooks/storefront/{id}` (spec: Phase 8.4) files a
low-priority ticket on the matching conversation when it can correlate
one. A `"docs"` integration (spec: Phase 9.3, Google Drive/SharePoint via
OAuth2 added in Phase 10.4) instead syncs Confluence/Notion/Drive/SharePoint
pages into the AI's own knowledge base via
`POST /admin/integrations/{id}/sync` (manual - no scheduler exists), so
product/policy answers can come from your real internal docs, not just
seeded markdown files. A `"stripe"` integration (spec: Phase 9.4) makes
refund approval call a real Stripe refund instead of only flipping this
app's own DB status, with Stripe's own webhook confirming completion
asynchronously - a tenant with none configured keeps today's DB-only
simulation. See `docs/DEPLOYMENT.md` for how to connect each one,
`docs/ARCHITECTURE.md`'s "Storefront-primary commerce routing",
"Inbound storefront webhooks", "RAG doc connectors", and "Payment
gateway (Stripe)", and `docs/SECURITY.md`'s "External
integrations" for the security model (including why WooCommerce lookup
is staff-triggered rather than autonomous, and external tool calls'
approval gate).

## Docker / Postgres+pgvector

```bash
make docker-up   # postgres (pgvector image) + redis + api, runs migrations on boot
```

## Web UI

`frontend/` is a Next.js app covering all three surfaces this API serves
- customer chat, staff ticket queue, and the admin console - with
role-based routing after login. See `frontend/README.md` for setup;
short version:

```bash
cd frontend
pnpm install
cp .env.example .env.local         # NEXT_PUBLIC_API_URL
pnpm dev                           # http://localhost:3000
```

Set `CORS_ALLOWED_ORIGINS` on the API (default already includes
`http://localhost:3000`) so the browser is allowed to call it - see
`docs/DEPLOYMENT.md`.

## Project layout

See `docs/ARCHITECTURE.md` for the full breakdown; the short version:

```
app/
  api/            FastAPI routes + Pydantic request/response schemas
  agents/         classifier, resolution agent, policy/grounding reviewer, escalation
  config/         Settings (env-driven) + the tool permission matrix
  domain/         enums, exceptions, SQLAlchemy models
  llm/            provider-agnostic LLMProvider protocol, router, profiles, health, factory, providers/
  observability/  structured logging, Prometheus metrics, retry policy, LangSmith tracing
  rag/            loaders, chunking, embeddings, retriever, reranker, ingestion
  repositories/   DB + vector-store data access
  security/       auth, authorization, PII redaction, prompt-injection defense
  services/       idempotency
  tools/          customer/order/payment/refund/subscription tools
  workflow/       LangGraph state, nodes, routers, graph assembly, runner
tests/            unit, integration, workflow, security, evaluation, load
migrations/       Alembic
scripts/seed/           sample data + knowledge base + seeding script
scripts/evaluation/     LangSmith dataset upload (spec §15)
demo_storefront/  a tiny standalone FastAPI app standing in for a real
                  external e-commerce storefront - not production code,
                  see "Demo storefront" below
```

### Demo storefront

`demo_storefront/` is a small, independent FastAPI service (its own
`docker-compose` service, its own in-memory data, reset on every
restart) that stands in for a real external e-commerce storefront - a
stable, committed target for the storefront-primary commerce routing
described above, replacing the throwaway fixtures used while developing
it. It is **not** part of the main app and has no auth, no persistence,
and no real payment/fulfillment logic - see `demo_storefront/main.py`.

```bash
make docker-up                # starts postgres, redis, api, and demo_storefront
make seed-storefront           # connects demo_storefront as the primary storefront integration
```

After that, order status/cancel/refund/exchange/address-change/
subscription-plan-change/payment-retry questions in the chat route
through the demo storefront instead of this app's own internal tables -
see `docs/DEPLOYMENT.md` for the full connection details and
`docs/ARCHITECTURE.md`'s "Storefront-primary commerce routing".
