# Environment Variables

Every backend env var this app reads, in one place, with what it's for and
what to actually set. The canonical source is `app/config/settings.py`
(backend) and `frontend/.env.example` (frontend) - this is a guided
tour of those, not a replacement for them.

**None of these are required to run the app.** Every default gives you a
fully working, zero-external-services system (SQLite + an in-memory vector
store + a deterministic mock AI). Everything below is either already
correct as-is, or only matters once you want a specific real capability.

**A note on how `.env` is actually read**, since it trips people up:
- Running locally (`make dev`): `app/config/settings.py` reads `.env`
  directly via `pydantic-settings` - every variable below takes effect.
- Running via `docker compose up`: the `api` service's `environment:`
  block in `docker-compose.yml` only passes through an explicit,
  hand-picked list of variables from your `.env` into the container - it
  does **not** forward your whole `.env` file. If a variable you set isn't
  in that list, Docker Compose silently ignores it. This doc flags exactly
  which variables that applies to.
- Several settings marked "**DB-seeded**" below are only read from `.env`
  the *very first time* a tenant boots (to seed the `system_settings`
  table) - after that, the database is the source of truth, and you
  change them via `PUT /api/v1/admin/settings/{key}` (ADMIN role) or the
  admin Settings page instead. Editing `.env` and restarting has no effect
  on an already-seeded deployment.

## App

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `APP_ENV` | `development` | Free-text label, currently only used in a startup log line. | Leave as-is; set `production` if you want it to show up in your logs. |
| `LOG_LEVEL` | `INFO` | Python logging level. | `INFO` for normal use, `DEBUG` when diagnosing an issue. |
| `API_HOST` | `0.0.0.0` | Interface uvicorn binds to (only used by `make dev` - Docker Compose's `command:` doesn't read this). | Leave as-is. |
| `API_PORT` | `8000` | Port uvicorn binds to (`make dev` only - Docker Compose hardcodes `8000` in `command:`/`ports:`). | Leave as-is unless `8000` is taken locally. |
| `CORS_ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated origins the browser frontend is allowed to call this API from. **Not passed through in `docker-compose.yml`** - a Docker Compose deployment always uses this default regardless of what you set. | Add your real frontend URL(s) here for `make dev`; edit `docker-compose.yml` directly if you need a different value under Docker Compose. |

## Database & storage backends

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./data/support.db` | Main database connection string. **Not used at all under Docker Compose** - `docker-compose.yml` hardcodes the real Postgres URL for the `api` service. | Leave as SQLite for `make dev`; for a real deployment outside Docker Compose, point at a real Postgres instance (`postgresql+asyncpg://user:pass@host:5432/db`). |
| `CHECKPOINT_BACKEND` | `sqlite` | Where LangGraph stores paused (awaiting-approval) workflow state: `sqlite` (single API instance only) or `postgres` (safe across multiple instances, reuses `DATABASE_URL`). | Leave as `sqlite` for one instance; set `postgres` before running more than one API instance. |
| `CHECKPOINT_DB_PATH` | `./data/checkpoints.db` | File path for the SQLite checkpointer. Only matters when `CHECKPOINT_BACKEND=sqlite`. | Leave as-is. |
| `VECTOR_BACKEND` | `memory` | Where the knowledge-base vector index lives: `memory` (process-local, resets on restart) or `pgvector` (durable, shared, needs Postgres). **Docker Compose hardcodes `pgvector`** for the `api` service regardless of this value. | Leave as `memory` for quick local testing; `pgvector` for anything you want to persist or share across instances. |
| `VECTOR_DIMENSIONS` | `384` | Embedding vector size - must match whatever `Embedder` you're actually using. **Not passed through in Docker Compose.** | Leave as-is unless you swap in a real embeddings model with a different output size. |

## AI / LLM providers

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `MOCK_LLM` *(DB-seeded)* | `true` | `true` = every AI call goes through a deterministic, keyword-matching mock (no API key, no cost, what tests run against). `false` = real calls to the providers below. | Keep `true` while developing/testing; set `false` once you have real provider keys and want real AI responses. After first boot, change via the admin Settings page instead of `.env`. |
| `DEFAULT_LLM_PROVIDER` *(DB-seeded)* | `google` | Which provider handles a call first when `MOCK_LLM=false`. | `google` is a good default (cheap, fast model already configured below). |
| `FALLBACK_LLM_PROVIDER` *(DB-seeded)* | `xai` | Which provider a call fails over to if the default one errors out. | Leave as `xai`, or `anthropic` if you'd rather fail over to Claude. |
| `GOOGLE_API_KEY` | *(blank)* | Real secret - **always env-only, never DB-backed.** Needed for any call routed to Google. | Get one from [Google AI Studio](https://aistudio.google.com/apikey) if you want real Gemini responses. |
| `GOOGLE_MODEL` | `gemini-3.1-flash-lite` | Which Gemini model to call. **Not passed through in Docker Compose** (hardcoded to this default there). | Leave as-is; it's a good cost/quality balance for this workload. |
| `XAI_API_KEY` | *(blank)* | Real secret - env-only. Needed for any call routed to xAI. | Get one from [x.ai](https://x.ai) if you want Grok as your default/fallback. |
| `XAI_MODEL` | `grok-4-fast` | Which Grok model to call. Not passed through in Docker Compose. | Leave as-is. |
| `ANTHROPIC_API_KEY` | *(blank)* | Real secret - env-only. Optional third provider, usable as `DEFAULT_LLM_PROVIDER`/`FALLBACK_LLM_PROVIDER=anthropic`. | Only set this if you specifically want Claude in the rotation. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | Which Claude model to call. Not passed through in Docker Compose. | Leave as-is. |
| `LLM_BUDGET_USD_PER_RUN` *(DB-seeded)* | *(blank = unlimited)* | Caps estimated LLM spend per workflow run - once exceeded, the run escalates to a human instead of making more calls. | Leave blank unless you want a hard cost ceiling per conversation turn. |

## LangSmith tracing (optional)

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `LANGSMITH_TRACING` | `false` | Turns on request tracing to LangSmith. Both this and the key below must be set. | Leave `false` unless you're actively debugging prompts/traces. |
| `LANGSMITH_API_KEY` | *(blank)* | Real secret - env-only. | Get one from [smith.langchain.com](https://smith.langchain.com) if you turn tracing on. |
| `LANGSMITH_PROJECT` | `customer-support-workflow` | Project name traces are grouped under. Not passed through in Docker Compose. | Leave as-is, or rename to match your own LangSmith project. |

## Auth & credential encryption

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `JWT_SECRET` | `change-me-in-production` | Signs every customer and staff JWT. | **Must** be a real random secret before any real deployment - anyone who knows this can forge tokens. Generate one with e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`. |
| `JWT_ALGORITHM` | `HS256` | JWT signing algorithm. Not passed through in Docker Compose. | Leave as-is. |
| `JWT_EXPIRY_MINUTES` | `60` | How long a customer/staff token stays valid. Not passed through in Docker Compose. | Leave as-is, or shorten for a stricter session policy. |
| `CREDENTIALS_ENCRYPTION_KEY` | *(blank)* | Dedicated key for encrypting every stored integration's credentials (JIRA/Stripe/etc. secrets). Blank means it's derived from `JWT_SECRET` instead - fine for dev, but rotating `JWT_SECRET` then also breaks every stored integration credential. | Set a dedicated random value (same generation method as `JWT_SECRET`) before connecting any real integration in production, so the two secrets can rotate independently. |

## Redis & rate limiting

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string, used for rate-limit counters when enabled. **Not used under Docker Compose** (hardcoded to the internal `redis` service there). | Leave as-is for `make dev` without Redis; point at a real Redis for a non-Docker-Compose production deployment running more than one API instance. |
| `USE_REDIS` | `false` | `true` = rate limits are shared across API instances via Redis; `false` = each instance counts independently (fine for exactly one instance). **Docker Compose hardcodes `true`** regardless of this value. | Leave `false` for a single instance; set `true` (and a real `REDIS_URL`) before running more than one instance outside Docker Compose. |
| `RATE_LIMIT_ENABLED` | `true` | Turns rate limiting on/off entirely. Not passed through in Docker Compose. | Leave `true`. |
| `RATE_LIMIT_PER_WINDOW` *(DB-seeded)* | `30` | Requests allowed per window per caller. | Leave as-is unless you have a specific throughput requirement. |
| `RATE_LIMIT_WINDOW_SECONDS` *(DB-seeded)* | `60` | Window length in seconds. | Leave as-is. |

## Confidence thresholds & retry/escalation behavior

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `CONFIDENCE_INTENT` *(DB-seeded)* | `0.80` | Minimum confidence to trust an intent classification without extra caution. | Leave as-is unless evaluation results tell you otherwise. |
| `CONFIDENCE_RETRIEVAL` *(DB-seeded)* | `0.30` | Minimum score for a retrieved knowledge document to count as relevant. Calibrated for the default lexical `HashingEmbedder`. | **Raise significantly (e.g. `0.75`)** if you swap in a real embeddings model - real semantic similarity scores run much higher than the lexical default. |
| `CONFIDENCE_RESPONSE` | `0.85` | Defined but **not currently referenced anywhere else in the codebase** - a real, un-wired setting, not a documentation oversight. | Setting it does nothing today; leave as-is. |
| `RETRY_MAX_ATTEMPTS` | `3` | Max retries for a failed LLM/tool call before giving up. Not passed through in Docker Compose. | Leave as-is. |
| `ESCALATION_MAX_FAILED_ATTEMPTS` *(DB-seeded)* | `2` | How many consecutive failures on a conversation before it auto-escalates to a human. | Leave as-is. |
| `SECURITY_REQUIRE_HUMAN_APPROVAL` | `true` | Master switch - if `false`, high-risk actions (refunds, external tool calls) execute without waiting for staff approval. Not passed through in Docker Compose. | **Keep `true` in any real deployment.** Only ever set `false` for isolated local testing of the automation path itself. |

## OAuth2 (Google Drive / SharePoint knowledge sync - optional)

Only needed if you connect a `docs`-type integration with `config.provider`
set to `"google_drive"` or `"sharepoint"`. Confluence and Notion use a
plain API token instead and need none of this.

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | *(blank)* | Credentials for an OAuth app registered in [Google Cloud Console](https://console.cloud.google.com/apis/credentials) (enable the Drive API, scope `drive.readonly`). | Set both if you want to sync a real Google Drive folder into the knowledge base. |
| `GOOGLE_OAUTH_REDIRECT_URI` | *(blank)* | Must exactly match the redirect URI registered on that OAuth app, pointing at this app's own `GET /api/v1/oauth/callback/google_drive` on its real public URL. | Set to `https://<your-domain>/api/v1/oauth/callback/google_drive`. |
| `MICROSOFT_OAUTH_CLIENT_ID` / `MICROSOFT_OAUTH_CLIENT_SECRET` | *(blank)* | Credentials for an app registration in [Azure AD](https://portal.azure.com) (Microsoft Graph API, scopes `Files.Read.All` + `offline_access`). | Set both if you want to sync a real SharePoint site. |
| `MICROSOFT_OAUTH_TENANT_ID` | `common` | Which Azure AD tenant to authenticate against (`common` works for most single-org setups). | Leave as `common` unless your Azure AD setup requires a specific tenant id. |
| `MICROSOFT_OAUTH_REDIRECT_URI` | *(blank)* | Must exactly match the redirect URI registered there, pointing at `GET /api/v1/oauth/callback/sharepoint`. | Set to `https://<your-domain>/api/v1/oauth/callback/sharepoint`. |

## Docker Compose-only host ports

These aren't read by the app at all - they only control which *host* port
each container's service is reachable on, so you can avoid clashing with
something else already running on your machine. Set them in `.env` before
`docker compose up`.

| Variable | Default | Maps to |
|---|---|---|
| `POSTGRES_HOST_PORT` | `5432` | The `postgres` container's `5432` |
| `REDIS_HOST_PORT` | `6379` | The `redis` container's `6379` |
| `DEMO_STOREFRONT_HOST_PORT` | `8100` | The `demo_storefront` container's `8000` |

## Things that are *not* env vars, even though it's a common assumption

Every external system integration (JIRA, WooCommerce, SMTP, a real
storefront, Stripe, Confluence, Notion, Google Drive, SharePoint, any
custom API, MCP servers) is configured **at runtime, per tenant**, via the
`Integration` API/admin UI - never an environment variable. This is
deliberate: it means connecting or reconfiguring one never needs a
redeploy. See `docs/USER_GUIDE.md`'s "Admin: the console" section and
`docs/API.md`'s "Integrations" section.

## Frontend

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Base URL of the backend the browser calls directly - this is public/client-visible, never a secret. Set in `frontend/.env.local`. | Point at wherever your backend is actually reachable from the browser (not from the frontend's own server - it's used client-side). |
