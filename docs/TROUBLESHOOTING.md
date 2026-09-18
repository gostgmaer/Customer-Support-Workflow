# Troubleshooting

## RAG queries return no results / `retrieved_documents` is always empty

- **Fresh process with `VECTOR_BACKEND=memory`**: check the startup log for
  `vector_index_warmed`. If `chunk_count` is 0, the DB has no
  `knowledge_chunks` yet - run `python scripts/seed/seed_data.py` (or your
  own call to `app.rag.ingest.ingest_knowledge_directory`) against the
  *same* `DATABASE_URL` the API process uses.
- **Threshold too high after changing the embedder**: `CONFIDENCE_RETRIEVAL`
  (default `0.30`) is calibrated for `HashingEmbedder` + the lexical-
  weighted reranker (see `docs/ARCHITECTURE.md`). If you swap in a real
  embeddings model, its cosine similarities will run much higher and you
  should raise this threshold back up (e.g. `0.75`) and turn
  `app.rag.reranker.rerank`'s `vector_weight` back up too.
- **Expired documents**: `app.rag.retriever._is_current` filters anything
  with a past `expiration_date` before scoring - if you expect a document
  to show up and it doesn't, check its frontmatter `expiration_date`.

## A refund/cancel confirmation loop seems "stuck" asking to confirm

Check that the previous assistant message actually contains the word
"confirm" (see `app.agents.confirmation.last_assistant_asked_to_confirm`)
and that your reply matches `interpret_confirmation_reply` (yes/no-style
wording). A message that changes the subject entirely (not a yes/no reply)
is treated as a new request, not a confirmation - by design.

## `POST /tickets/{id}/approve` returns "Ticket ... not found" or 422

- Confirm you're using the `ticket_id` and `workflow_run_id` from the
  `/messages` response that had `"status": "awaiting_approval"` - both are
  required and must match the same run.
- A ticket only accepts approve/reject while `status == "open"`; a
  double-approve or approving an already-rejected ticket returns a
  `VALIDATION_ERROR`.

## 401 on ticket endpoints

Ticket endpoints need a **staff** bearer token, not a customer one - log in
via `POST /api/v1/staff/login` first (see `docs/API.md`). A customer token
is rejected even though it's a well-formed JWT, because
`decode_staff_token` checks the `scope` claim is `"staff"` - see
`docs/SECURITY.md`. `make seed` creates a working staff login
(`agent_jane`).

## 429 on `/staff/login` after a few attempts

That's the brute-force guard (5 attempts / 5 minutes per username, see
`docs/SECURITY.md`), not a bug - wait for the window to pass, or in a test
environment call `InMemoryRateLimiter.reset()` (see
`tests/conftest.py::_reset_rate_limiter` for the pattern).

## 429 on `/support/messages`

`RATE_LIMIT_PER_WINDOW`/`RATE_LIMIT_WINDOW_SECONDS` (default 30/60s per
customer) was exceeded. Raise the limit, or set `RATE_LIMIT_ENABLED=false`
for local load testing - see `docs/SECURITY.md`.

## `sqlite3.OperationalError: database is locked`

SQLite serializes writes; under concurrent load switch `DATABASE_URL` to
Postgres (`make docker-up`) rather than tuning SQLite further - the
zero-setup SQLite path is for local development, not concurrent production
traffic.

## Tests are flaky / see data from a previous test

Every test gets its own SQLite file and in-memory vector store via the
autouse fixtures in `tests/conftest.py` (`_isolated_database`,
`_reset_in_memory_vector_store`). If you add a new fixture or bypass
`db_session`/`client`, make sure it goes through
`app.db.session.get_sessionmaker()` (which respects the per-test
`DATABASE_URL`) rather than caching its own engine/connection.

## Real LLM calls fail with `LLMError`, or responses still look like mock output

- **`MOCK_LLM` still true**: check `app_startup`'s log line - it prints
  `mock_llm`/`default_llm_provider`/`fallback_llm_provider`. `MOCK_LLM=true`
  is the zero-setup default and silently ignores `GOOGLE_API_KEY`/`XAI_API_KEY`
  entirely; you must set `MOCK_LLM=false` to actually call a real provider.
- **Missing API key**: `app.llm.factory.get_provider` raises `LLMError`
  immediately (not a network error) if the configured provider's API key
  env var is empty - check `GOOGLE_API_KEY`/`XAI_API_KEY`/`ANTHROPIC_API_KEY`
  matches whichever provider `DEFAULT_LLM_PROVIDER`/`FALLBACK_LLM_PROVIDER`
  names.
- **Both primary and fallback failed**: `app.llm.router._FailoverLLMProvider`
  tries the primary, then the fallback, then raises `LLMError` wrapping the
  last error - check the `llm_provider_failed` log lines (one per attempt)
  for the underlying cause per provider.
- **A provider keeps getting skipped**: `app.llm.health` marks a provider
  `DISABLED` after 6 consecutive failures and the router skips straight to
  the fallback without retrying it. It recovers to `HEALTHY` on the next
  success - if a provider was down and is now fine, the next successful
  call clears it automatically; there's no manual reset needed outside
  tests (`app.llm.health.get_health_registry().reset()`).
