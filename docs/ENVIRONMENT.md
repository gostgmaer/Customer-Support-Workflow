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
| `VECTOR_BACKEND` | `memory` | Where the knowledge-base vector index lives: `memory` (process-local, resets on restart) or `pgvector` (durable, shared, needs Postgres, uses a real `vector` column + HNSW index - see migrations 0013-0014). **Docker Compose hardcodes `pgvector`** for the `api` service regardless of this value. | Leave as `memory` for quick local testing; `pgvector` for anything you want to persist or share across instances. |
| `VECTOR_DIMENSIONS` | `768` | Embedding vector size - must match whatever `Embedder` you're actually using (768 matches `EMBEDDING_MODEL`'s default, Matryoshka-truncated output). **Not passed through in Docker Compose** - the pgvector column is hardcoded to `vector(768)` in migration 0013, so changing this alone would silently break `VECTOR_BACKEND=pgvector` without a matching new migration. | Leave as-is unless you swap in a real embeddings model with a different output size *and* write a migration to match. |
| `EMBEDDING_MODEL` | `models/gemini-embedding-2` | Real embedding model used when `MOCK_LLM=false` and `GOOGLE_API_KEY` is set (see `app.rag.embeddings.get_embedder`) - otherwise the deterministic `HashingEmbedder` fallback is used regardless of this value. | Leave as-is unless Google changes the recommended embedding model; verify the real output dimension against the live API before changing `VECTOR_DIMENSIONS` to match. |
| `CHUNK_SIZE` | `800` | Max characters of a chunk sub-split within one markdown-heading section (`app.rag.chunking`) - character-based, not token-based. | Leave as-is; raise if your knowledge base has unusually long unstructured sections. |
| `CHUNK_OVERLAP` | `120` | Character overlap between adjacent sub-split chunks. | Leave as-is. |

## Original-file storage for KB uploads (spec: multi-provider, R2 default)

Where the *original* file behind a Knowledge Base upload (`POST /api/v1/knowledge/upload`) is
kept, separately from its extracted text (which always lands in the database regardless of
this section). Storing the original file is optional and best-effort - a misconfigured or
unreachable provider never fails the upload itself, it just means `has_original_file` stays
`false` for that article. See `scripts/storage/migrate_file_storage.py` for moving already-
uploaded files onto a newly-selected provider.

| Variable | Default | Purpose | Recommendation |
|---|---|---|---|
| `FILE_STORAGE_PROVIDER` | `r2` | Which provider is active: `r2`, `s3`, `azure`, or `local`. One at a time - this isn't a fallback chain. | `local` for zero-setup dev (writes under `LOCAL_STORAGE_DIR`, no account needed); pick a real cloud provider for production. |
| `LOCAL_STORAGE_DIR` | `./data/uploads` | Where `local` writes files. Only matters when `FILE_STORAGE_PROVIDER=local`. | Leave as-is for dev; not meant for production use (single-instance, no redundancy). |
| `R2_ACCOUNT_ID` | *(blank)* | Cloudflare account id - used to build R2's account-specific S3-compatible endpoint. | Required if `FILE_STORAGE_PROVIDER=r2`. |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | *(blank)* | R2 API token credentials (create one under R2 → Manage API Tokens). | Required if `FILE_STORAGE_PROVIDER=r2`. |
| `R2_BUCKET` | *(blank)* | The R2 bucket to upload into. | Required if `FILE_STORAGE_PROVIDER=r2`. |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | *(blank)* | Real AWS IAM credentials. | Required if `FILE_STORAGE_PROVIDER=s3`. |
| `S3_BUCKET` | *(blank)* | The S3 bucket to upload into. | Required if `FILE_STORAGE_PROVIDER=s3`. |
| `S3_REGION` | `us-east-1` | The bucket's AWS region. | Match whatever region your bucket actually lives in. |
| `AZURE_STORAGE_CONNECTION_STRING` | *(blank)* | Full Azure Storage account connection string. | Required if `FILE_STORAGE_PROVIDER=azure`. |
| `AZURE_STORAGE_CONTAINER` | *(blank)* | The blob container to upload into. | Required if `FILE_STORAGE_PROVIDER=azure`. |

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
| `CONFIDENCE_RETRIEVAL` *(DB-seeded)* | `0.30` | Minimum score for a retrieved knowledge document to count as relevant. The score checked against this threshold is `app.rag.reranker.rerank`'s blended vector+lexical score, **not** a raw embedding cosine similarity or the RRF fusion score - hybrid retrieval (Phase 11) changes which candidates reach this check, not the scale of the number checked against it. | Re-tune against real query/answer quality once real embeddings (`EMBEDDING_MODEL`) are live in your deployment - don't assume this default still fits without checking. |
| `RERANK_SEMANTIC_VECTOR_WEIGHT` | `0.85` | `rerank()`'s vector-score weight when a real semantic embedder is active (unused for the `HashingEmbedder` fallback, which keeps `rerank()`'s own lexical-dominant `0.35`). Live-verified: a query sharing several literal words with the wrong document needed this above ~0.84 for a real, clearly-stronger cosine match (0.745 vs 0.675) to actually win. **Not passed through in Docker Compose.** | Leave as-is unless real-query testing against your own corpus shows a different value fits better. |
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
