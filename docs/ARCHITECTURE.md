# Architecture

## Request flow

```
POST /api/v1/support/messages
        |
        v
app.workflow.runner.run_workflow
        |  creates a WorkflowRun row, builds initial SupportState,
        |  compiles the LangGraph graph with a checkpointer,
        v  invokes it with thread_id = workflow_run_id
+-------------------------------------------------------------+
| LangGraph StateGraph (app.workflow.graph)                    |
|                                                               |
| validate_input -> load_conversation -> classify_intent ->    |
| classify_priority -> detect_sentiment -> route_request       |
|   -> {knowledge_search|customer_data|action_required|        |
|        human_escalation}                                     |
|   -> resolve_issue -> human_approval_gate -> policy_check ->|
|      grounding_check -> response_review                      |
|        -> approved: send_response                            |
|        -> rejected: regenerate -> policy_check (loop, capped)|
|   -> send_response -> save_outcome -> END                    |
+-------------------------------------------------------------+
        |
        v
SupportMessageResponse {status, response, requires_human, ticket_id?}
```

Each HTTP request to `/messages` is one graph invocation, keyed by a fresh
`workflow_run_id` (used as the LangGraph thread id). Conversation-level
continuity (history, the previously-classified intent) is read from
Postgres/SQLite in `load_conversation`, not from LangGraph checkpoint state
carried across requests - so multiple messages in the same conversation are
independent graph runs that happen to share a `conversation_id`. The
*checkpointer* exists specifically for the human-approval interrupt (see
below): a single run can pause mid-graph and resume later.

## Why LangGraph nodes, not one agent loop

Per the spec's rule 17 ("prefer deterministic business logic over autonomous
LLM decisions") and §31 ("do not create a single autonomous agent
responsible for everything"), the LLM is only asked to do three kinds of
work:

1. **Classify** (intent/priority/sentiment/policy/grounding/review) via
   structured output (`app.llm.base.LLMProvider.generate_structured`).
2. **Phrase** a response from facts that were already deterministically
   gathered (`app.agents.resolution.draft_response`).
3. Nothing else. It never decides *which* tool to call or *whether* an
   action is authorized - `app.agents.resolution.INTENT_RESOLVERS` maps
   intent to resolver function, and `app.security.authorization` /
   `app.config.policies` enforce the permission matrix independently of
   anything the LLM says.

## LLM provider router (spec §3-8)

Every node that needs a model calls `deps.llm_router.get_model(purpose)`
(`app.workflow.deps.WorkflowDeps.llm_router`, built once per request in
`app.workflow.runner._build_deps`) - nowhere in `app/agents/` or
`app/workflow/` imports a vendor SDK or even knows which provider is
actually serving a given call.

```
caller: deps.llm_router.get_model("intent_classification")
              v
app.llm.router.LLMRouter.get_model(purpose)
   MOCK_LLM=true?  -> yes -> app.llm.providers.mock.MockLLMProvider (always)
              v no
   app.llm.profiles.PURPOSE_TO_PROFILE[purpose] -> profile name
              v
   app.llm.profiles.get_profiles()[profile] -> ModelProfile(provider, model)
              v
   _FailoverLLMProvider(primary=profile, fallback=profiles["fallback"])
        .generate() / .generate_structured()
              v
        try primary via app.llm.factory.get_provider(primary.provider)
           success -> app.llm.health records success, return
           failure -> app.llm.health records failure, log, try fallback
                         (skipped if health already says DISABLED)
              v
        both failed -> raise LLMError (caller/workflow escalates to human)
```

- **Profiles** (`app.llm.profiles.get_profiles`) map a profile name
  (`default`/`fallback`/`classification`/`reasoning`/`response`) to a
  provider+model pair read entirely from `Settings` - never hard-coded.
  `DEFAULT_LLM_PROVIDER=google` (Gemini) / `FALLBACK_LLM_PROVIDER=xai`
  (Grok) are the out-of-the-box values; `PURPOSE_TO_PROFILE` in the same
  file maps each call site's purpose to a profile (classification tasks ->
  `classification`, policy/grounding/review -> `reasoning`, drafting the
  customer-facing reply -> `response`).
- **Providers** (`app/llm/providers/`): `google.py`/`xai.py`/`anthropic.py`
  are each a ~15-line `LangChainChatProvider` (shared base in
  `_langchain_base.py`) wrapping one LangChain `BaseChatModel`. Adding
  OpenAI/Azure/Bedrock/Ollama/OpenRouter/etc. is the same pattern - write
  the file, register it in `app.llm.factory._BUILDERS`, done; nothing else
  changes.
- **Health** (`app.llm.health`): a process-local HEALTHY/DEGRADED/DISABLED
  counter per provider. A DISABLED primary is skipped in favor of the
  fallback outright rather than being retried every call.
- **Mock mode** (`MOCK_LLM=true`, the zero-setup default): the router
  returns `MockLLMProvider` for every purpose, bypassing profiles/failover
  entirely - the whole system runs offline with zero API keys (spec §48).

## Human-in-the-loop (spec §18)

`app.workflow.nodes.human_approval.human_approval_gate` calls LangGraph's
`interrupt()` when `state["awaiting_approval"]` is set - after a refund
request is created (refunds always require human approval per the policy
matrix in `app.config.policies`), or after `app.agents.external_tools`
proposes an MCP or OpenAPI tool call (see "External tool-call fallback"
below). This pauses the graph and persists the pause via a real
checkpointer (`app.workflow.runner.get_checkpointer`), not an in-memory
flag - the pause survives a process restart. `AsyncSqliteSaver` (a local
file, `CHECKPOINT_DB_PATH`) is the zero-setup default, correct for a
single instance; `CHECKPOINT_BACKEND=postgres` (spec: Phase 9.1a)
switches to `AsyncPostgresSaver`, reusing `DATABASE_URL`, so any API
instance can resume a run any other instance paused - see
docs/DEPLOYMENT.md's "Production architecture" for when this matters and
how it's initialized. When it pauses,
`run_workflow` files a `SupportTicket` (status `open`) and returns
`{"status": "awaiting_approval", "ticket_id": ...}` to the caller.

`POST /api/v1/support/tickets/{id}/approve` (or `/reject`) resumes the exact
same graph run via `graph.ainvoke(Command(resume={"approved": bool}), config)`
against the same `thread_id`, and updates the ticket's status. See
`app.workflow.runner.resume_workflow`. For a refund, the state-changing
work already happened before the gate (the `RefundRequest` row was
already created, `status="pending"`) - approval/rejection here changes
the ticket's status *and* (spec: Phase 9.4a)
`RefundRequest.status` itself, via `human_approval_gate`'s
`_update_refund_status_after_decision` (finds the refund created
earlier in this same run through `state["tool_results"]`'s
`create_refund_request` entry, then
`RefundRepository.update_status(refund, "approved"|"rejected")`) - a
real, previously-unfixed bug meant this row stayed permanently
`"pending"` forever regardless of what staff decided, for this
project's entire history until this fix. For an external tool call, the
real work happens *inside* this resume:
`human_approval_gate`'s `_execute_approved_external_call` dispatches on
the proposal's `source` to either `mcp_client.call_tool` or
`openapi_client.call_operation`, only now, for the first and only time
(see "External tool-call fallback").

**Ticket review UI** (spec: Phase 8.2): `SupportTicket.pending_call`
(the proposed integration/tool/arguments, populated from the exact
payload `human_approval_gate` passed to `interrupt()` - `None` for a
refund ticket) and `SupportTicket.execution_result` (the real
response/error after execution, previously discarded once folded into
`resolution_facts`/`draft_response` text) make the whole exchange
inspectable on the ticket itself rather than only as flattened prose.
`ApproveTicketRequest.arguments` lets staff override some or all of the
proposed arguments before approving; `_execute_approved_external_call`
shallow-merges the override in and re-validates the merged result
against the tool's JSON Schema (carried on the proposal since it was
first made) before dispatch - see `docs/SECURITY.md`'s "External tool
calls" for why re-validation, not just merging, matters here.

## Multi-turn confirmation vs. human approval - two different gates

These are deliberately separate mechanisms:

- **Customer confirmation** (spec §12's "Customer Confirmation" column): a
  plain conversational round-trip. `app.agents.resolution` drafts a
  "please confirm you want to cancel/refund X" reply and does **not** call
  the mutating tool yet. The next message is checked by
  `app.agents.confirmation.customer_already_confirmed`.
- **Human approval** (spec §12's "Human Approval" column): a LangGraph
  `interrupt()`, requiring a human agent to call the ticket approve/reject
  endpoint - a different actor, a different channel, and (per the policy
  matrix) required even after the customer has already confirmed.

A subtlety worth calling out: a short reply like "yes" carries none of the
original request's keywords. `app.workflow.nodes.classify.classify_intent_node`
deterministically keeps the previous turn's intent (read from the
`Conversation.intent` column via `previous_intent` in state) whenever the
last assistant message asked to confirm something and this message reads as
a yes/no reply - see `app.agents.confirmation`. This avoids the classifier
guessing UNKNOWN for a bare "yes" and derailing a pending refund.

## Intent classification reliability (spec: Phase 9.2)

`app.agents.classifier.classify_intent` asks the model to pick exactly
one of `Intent`'s ~24 values. For most of this project's history, the
literal prompt text (`_INTENT_SYSTEM_RULES`) said "classify into exactly
one intent from the allowed list" without ever actually naming any of
them, and `IntentClassification.intent` (`app.agents.schemas`) was a
bare `str` with no enum constraint - so the model had to classify into a
taxonomy it was never shown. This was the root cause of a real,
previously-undiagnosed bug: three separate live-testing incidents
(Phase A2, Phase 8.3's `EXCHANGE`, Phase 8.4), all involving a message
with a dash-separated order-id token (`ORD-9001`/`ORD-1002`/`ORD-1001`),
misclassified as `UNKNOWN` - each logged at the time as "a live-testing
finding, not a bug" and cross-referenced as "the same variance," never
actually traced to a cause.

**The fix, both ends**: `_INTENT_SYSTEM_RULES` now lists every `Intent`
value by name, built from the enum itself
(`", ".join(i.value for i in Intent)`) so it can never silently drift
out of sync again the way it did when Phase 8.3 added four new intents
that this prompt never mentioned. `IntentClassification.intent` is now
`Literal[tuple(i.value for i in Intent)]` - since `generate_structured`
goes through LangChain's `with_structured_output(schema, include_raw=True)`,
this becomes a real JSON-schema `enum` constraint the model is forced to
choose from, not just documentation. `classify_intent` also does one
bounded retry, specifically when the first call lands on `UNKNOWN` (or
fails schema validation outright - a provider that doesn't strictly
enforce the constraint could still return an out-of-taxonomy string,
which LangChain surfaces as an `LLMError` rather than an invalid
`IntentClassification`): it re-asks once with an amended message asking
the model to reconsider against the same list. Both failure paths
(second attempt also `UNKNOWN`, or two schema-validation failures in a
row) fall back to a safe `UNKNOWN` classification rather than letting an
exception propagate and take down the workflow run - matching this
codebase's "escalate rather than crash" posture used everywhere else.

Live-verified against real Gemini: all three historical failure
messages, re-run 4-8 times each through the fixed classifier, now
consistently classify correctly (`ORDER_STATUS`/`ORDER_STATUS`/`EXCHANGE`
respectively) with no observed flakiness. The three messages are also
now permanent regression cases in `tests/evaluation/dataset.py::EVAL_CASES`
(this file's own docstring had instructed exactly this - "extend
whenever a real production failure is diagnosed" - for three phases
running before it actually happened).

## RAG pipeline (spec §8-9; retrieval upgrade: Phase 11)

```
scripts/seed/knowledge/*.md (YAML frontmatter + body)
        v  app.rag.loaders.load_knowledge_directory
LoadedDocument (title, category, version, effective/expiration dates, text)
        v  app.rag.chunking.build_chunks (LangChain: heading-aware + size-bounded)
DocumentChunk[] (section_path, content_hash, token_count, chunking_version)
        v  app.rag.embeddings.get_embedder().embed_batch
embeddings (LangChainEmbedder/gemini-embedding-2, or HashingEmbedder fallback)
        v  app.repositories.vector_store (upsert)
KnowledgeDocument/KnowledgeChunk rows (DB, source of truth)
  + vector store entries (search index: real pgvector column + HNSW,
    or in-memory numpy, per VECTOR_BACKEND)
```

**Embeddings** (`app.rag.embeddings.get_embedder`): a real semantic model
(`LangChainEmbedder`, wrapping `langchain_google_genai.GoogleGenerativeAIEmbeddings`,
`EMBEDDING_MODEL` default `models/gemini-embedding-2`, truncated to
`VECTOR_DIMENSIONS` via the model's own Matryoshka output-dimensionality
support - verified against the real Google API, not assumed) is used
whenever `MOCK_LLM=false` and `GOOGLE_API_KEY` is set. Otherwise
`HashingEmbedder` (deterministic feature-hashing bag-of-words, purely
lexical token-overlap - **not semantic**) is the zero-setup/offline
fallback, matching how a real vs. mock LLM provider is already selected
elsewhere. Real embeddings are a different vector space than hash-based
ones - switching requires re-embedding the existing corpus once via
`scripts/rag/reembed_all.py` (pgvector backend only; the in-memory
backend just needs an API restart, since its startup warm-up already
re-embeds with whatever embedder is currently configured).

**Chunking** (`app.rag.chunking.build_chunks`): `MarkdownHeaderTextSplitter`
splits on `#`/`##`/`###` headings first (keeping a GFM table/list intact
within its section), then `RecursiveCharacterTextSplitter` further splits
any section still over `CHUNK_SIZE` (default 800 chars, `CHUNK_OVERLAP`
default 120 - character-based, not token-based: `tiktoken` is not a real
dependency of this project, so `token_count` in chunk metadata is an
approximation, chars/4). Each chunk's metadata carries `section_path`
(the heading trail), `content_hash` (blake2b of the chunk text - used
for ingest-time dedup, see below), `token_count`, and `chunking_version`.

**Vector storage** (`app.repositories.vector_store`): `VECTOR_BACKEND=memory`
(default) is a process-local numpy brute-force cosine store, fine for a
small per-tenant corpus. `VECTOR_BACKEND=pgvector` uses a real `vector`
column with an HNSW index (`ORDER BY embedding_vec <=> :query LIMIT
:top_k`, migrations 0013-0014) - previously this backend stored
embeddings as plain JSON and scored every row in the namespace in
Python with no LIMIT at all, a real O(n) brute-force scan despite the
`pgvector/pgvector:pg16` image already shipping the extension unused.

**Hybrid retrieval** (`app.rag.retriever.Retriever.retrieve`):

1. Embeds the query, then runs a **vector search and an independent
   keyword search in parallel** - `VectorRepository.search` (semantic)
   and `.search_keyword` (full-text: `ts_rank`/`plainto_tsquery` over a
   generated `tsvector` column for pgvector, `app.rag.reranker.lexical_overlap`
   over the in-memory backend's small candidate set). A document the
   embedding step fails to surface can still be recovered by an exact
   keyword match - previously impossible, since reranking only ever
   rescored what vector search already found.
2. Fuses the two candidate lists via **Reciprocal Rank Fusion**
   (`app.rag.reranker.reciprocal_rank_fusion`, `k=60`, the standard
   default) - this only decides *which* chunks matter and their relative
   order. Each candidate's score used downstream is its real vector
   cosine similarity when vector search found it, or `0.0` when it was
   recovered by keyword search alone (RRF's own fused score lives on an
   incompatible scale for the confidence threshold below - feeding it in
   directly was tried and confirmed, live, to silently collapse every
   combined score under threshold).
3. **Filters out expired documents** (`expiration_date` in the past)
   before any further scoring - an expired policy can never outrank a
   current one because it is never scored at all (spec §8).
4. Reranks survivors with `app.rag.reranker.rerank`, blending the
   vector/zero score above with lexical overlap. The blend weight is no
   longer a single constant: `HashingEmbedder` keeps `rerank()`'s own
   lexical-dominant `0.35` default (its cosine scores are too coarse to
   trust further), but a real embedder uses `RERANK_SEMANTIC_VECTOR_WEIGHT`
   (default `0.85`) instead. **This was a real bug caught by live
   testing, not a design choice made upfront**: with real
   `gemini-embedding-2` vectors active, the query "How many days can I
   return an item within of purchase?" correctly scored Refund Policy
   highest on cosine similarity alone (0.745 vs Shipping Policy's 0.675)
   - but Shipping Policy's text happens to share several literal words
   with the query ("days", "within", "purchase"), giving it more than
   double the lexical-overlap score. At the old `0.35` weight this
   lexical false-positive won outright; the weight needs to exceed
   ~0.84 before the genuinely-stronger semantic match wins. `CONFIDENCE_RETRIEVAL`
   (default `0.30`) still needs re-tuning against real query/answer
   quality once real embeddings are live in a given deployment.
5. Deduplicates near-identical chunks and returns the top `k`. An empty
   result is a real signal, not a bug: `app.agents.resolution.resolve_from_knowledge`
   turns "no documents found" into an escalation instead of asking the LLM
   to answer from nothing (spec §9, §34 scenario 4).

**Ingest-time dedup** (`app.rag.ingest.ingest_documents`, spec: Phase 11
Tier 2.3): a document re-synced with a bumped `version` (external doc
sources only - local markdown files are hand-versioned and skip
entirely on a repeat ingest) is now diffed by `content_hash` rather than
having every chunk wiped and rebuilt: a chunk whose text is byte-identical
to what's already stored is left alone (no re-embed call), only chunks
whose hash no longer appears are deleted, and only genuinely new/changed
chunks are embedded. A version bump that only changed page metadata
(not content) now reports `chunks_ingested: 0` - a real, measurable
cost saving on re-sync, not just a theoretical one.

**Observability**: per-stage Prometheus histograms
(`EMBEDDING_LATENCY`, `VECTOR_SEARCH_LATENCY`, `KEYWORD_SEARCH_LATENCY`,
`RERANK_LATENCY`, alongside the existing `RETRIEVAL_LATENCY`) plus one
structured `rag_retrieval` log per request (candidate counts at each
stage, never full chunk content) - previously only one combined latency
histogram and a hit/miss counter existed for the entire pipeline.

**Evaluation**: no Recall@K/MRR/NDCG numbers are reported for this
upgrade - there is no existing labeled retrieval-evaluation dataset in
this codebase, and fabricating query/expected-chunk pairs to produce
before/after numbers would misrepresent measurement that didn't happen.
See `docs/EVALUATION.md` for what was actually measured (a live,
reproducible query/answer comparison) and what is explicitly marked
`NOT MEASURED`.

### Why an in-memory vector store needs a startup step

`VECTOR_BACKEND=memory` (the zero-setup default) is **process-local** - it
does not survive a process restart the way SQLite does. `scripts/seed/seed_data.py`
ingests documents once (writing both the DB rows and, incidentally, that
process's own in-memory index). A freshly started API process instead calls
`app.rag.ingest.warm_vector_index_from_db` on startup (see `app.main`'s
`lifespan`), which re-embeds the already-ingested DB rows into its own
in-memory index without touching the DB. `VECTOR_BACKEND=pgvector` skips
this entirely since embeddings are already durably stored.

### RAG doc connectors: Confluence + Notion (spec: Phase 9.3)

An `Integration.type: "docs"` row (`config.provider: "confluence"|"notion"`)
lets a tenant pull product-info/policy content from a real external doc
source into the same knowledge base local markdown files use, rather
than requiring everything to be a hand-maintained file in
`scripts/seed/knowledge/`. `app.integrations.docs_connector.get_docs_client`
dispatches to `ConfluenceClient` (`basic` auth - email + API token,
identical to this codebase's existing JIRA client) or `NotionClient`
(`bearer` auth - an internal integration token, plus a fixed
`Notion-Version` header every request needs, added per-request rather
than as a `build_http_client` change since it's Notion-specific).
`config.space_key`/`config.database_id` syncs every page in a
space/database; `config.page_ids` syncs an explicit list instead - at
least one is required per provider.

Both clients return `app.rag.loaders.LoadedDocument` directly - the
exact shape the local markdown loader already produces - so
`app.rag.docs_ingest.sync_docs_integration` reuses
`app.rag.ingest.ingest_documents` (the dedupe/chunk/embed/upsert core
extracted out of `ingest_knowledge_directory` for exactly this reuse,
rather than a second copy of that pipeline) instead of a parallel
ingestion path. One real behavioral difference from local files:
`update_on_version_change=True` - a live external source can change
silently between syncs (unlike a deliberately hand-versioned markdown
file), so a page whose `version` (Confluence: numeric page version;
Notion: `last_edited_time`, which has no numeric equivalent but serves
the same "did this change" role) differs from what's stored gets its old
chunks deleted and replaced, not silently skipped or duplicated.

Confluence's storage-format body is XHTML - `app.integrations.html_text.html_to_text`
strips it via a small stdlib-only (`html.parser.HTMLParser`) parser, not
a new dependency (a repo-wide check found zero existing HTML-stripping
utility and zero `beautifulsoup4`/`html2text`/`lxml` dependency
anywhere). Notion's blocks are already structured JSON, so no stripping
is needed there.

**Sync is manual, not scheduled**: `POST /api/v1/admin/integrations/{id}/sync`
(admin-only) is the entire mechanism - no scheduler/cron/Celery exists
anywhere in this codebase, and none was added for this. An admin
re-syncs on demand.

**Live-verified** against a real HTTP server (not just respx-mocked unit
tests) implementing the exact Confluence Cloud v2 endpoints
`ConfluenceClient` calls, reached from the real running `api` container:
a real `docs` integration was created via the real admin API, `POST
.../test` correctly reported "Connected - 1 document(s) available:
Refund Policy", `POST .../sync` correctly ingested it
(`{"chunks_ingested": 1}`), and the synced content
(`source: "confluence:111"`) was confirmed genuinely retrievable
alongside the seeded local knowledge base through the real running
app's actual `Retriever`/vector store - not a mock.

**Explicit fixture-only boundary for the automated test suite**: no real
Confluence/Notion workspace exists to verify a live sync against in
CI/unit tests - `tests/unit/test_docs_connector.py` and
`tests/integration/test_docs_sync_route.py` are built entirely against
respx-mocked fixture responses shaped to match each provider's real,
public API documentation. The one live-HTTP verification above used a
throwaway fixture server standing in for real Confluence, the same
"a realistic fixture standing in for one" allowance this project's own
verification practice already established for Phase A2's storefront
work - not a substitute for eventually connecting a genuine workspace.

### RAG doc connectors: Google Drive + SharePoint, OAuth2 (spec: Phase 10.4)

The two remaining doc providers, built on new OAuth2 (authorization-code
+ refresh-token) infrastructure this app never needed before -
Confluence/Notion's `basic`/`bearer` credentials never expire, so
`Integration.encrypted_credentials` was always a static blob until now.
`config.provider: "google_drive"|"sharepoint"`, `auth_type: "oauth2"`.

**Connecting one** is a three-step flow, not a single "paste your
credentials" form like every other integration type: (1) an admin
creates the `docs` integration with `config.folder_id`/`config.file_ids`
(Drive) or `config.drive_id`/`config.folder_path`/`config.file_ids`
(SharePoint) but no real credentials yet; (2)
`GET /admin/integrations/{id}/oauth/authorize` (staff-authenticated,
lives in `app.api.routes.integrations` alongside `/test`/`/sync`)
redirects the admin's browser to Google/Microsoft's real consent
screen; (3) after consent, the provider redirects to
`GET /api/v1/oauth/callback/{provider}` (`app.api.routes.oauth_callback`,
mounted directly in `app.main` - **genuinely unauthenticated**, a third
distinct inbound-auth story in this codebase alongside staff JWTs and
the HMAC-signed webhooks above, since a browser redirect from
Google/Microsoft's own server carries no staff JWT at all), which
exchanges the authorization code for real tokens and stores them via
the same `encode_credentials` every other integration type already
uses - no schema change, since `encrypted_credentials` was always
arbitrary Fernet-encrypted JSON, not a fixed shape.

**CSRF via a signed `state`, not routed through customer/staff JWTs**:
`app.security.oauth2.sign_state`/`verify_state` is a small, dedicated
HMAC-signed blob (`{integration_id, nonce, ts}`, reusing the same
`hmac`/`secrets` primitives already established in
`app.security.webhooks`) with a 10-minute tolerance window - a `state`
value has no "customer"/"staff"/"system" scope concept, so adding a
fourth JWT scope to `app.security.auth` would have been more disruptive
than this small, purpose-built helper.

**Token refresh, kept out of `build_http_client`'s hot path**:
`build_http_client` (`app.integrations.base`) stays fully synchronous
and unchanged in how every existing call site uses it (`async with
build_http_client(integration) as client:`) - it just reads whatever
`access_token` is currently stored. A new, separate
`ensure_fresh_oauth2_token(integration, session)` checks `expires_at`
and refreshes-then-re-persists (in memory - the caller commits,
mirroring how `app.integrations.health`'s openapi/mcp branches already
mutate `integration.config` in memory and leave committing to their
caller) *before* `build_http_client` is ever called - `GoogleDriveClient`/
`SharePointClient` (`app.integrations.docs_connector`) call it as the
first line of `fetch_documents()`. This is why only they (and
`get_docs_client`) need a `session` parameter Confluence/Notion never
did - the ripple from adding OAuth2 stayed contained to the one place
that actually needs to refresh a token, not the ~10 other
`build_http_client` call sites across this codebase, none of which use
`oauth2` auth.

**Deliberate v1 content limitations, not oversights**: `GoogleDriveClient`
only fetches actual Google Docs (via Drive's `files.export` to plain
text) - other file types (PDFs, images, spreadsheets) are silently
skipped, since converting them to text needs a real format converter
this pass doesn't attempt. `SharePointClient` similarly only fetches
`.txt`/`.md` files via Graph's raw content endpoint - Word/PDF/Excel
documents need the same kind of converter. Both mirror
`app.integrations.docs_connector`'s existing duck-typed
`__init__(integration, ...)` + `async fetch_documents()` interface, no
new abstraction needed.

**Explicit cannot-live-verify boundary, matching Stripe/Confluence/Notion's
own already-accepted precedent**: no real Google Cloud OAuth app or
Azure AD app registration exists yet - `tests/unit/test_oauth2.py` and
`tests/unit/test_docs_connector.py`'s Drive/SharePoint cases are built
entirely against respx-mocked token/content endpoints. The closest
available live check was run instead: with `GOOGLE_OAUTH_CLIENT_ID`
left blank (the zero-setup default), a real `state`-signed request to
`GET /api/v1/oauth/callback/google_drive` against the real running
container made a genuine HTTPS call to `https://oauth2.googleapis.com/token`
and correctly received/parsed Google's real
`400 {"error": "invalid_request", "error_description": "Could not
determine client ID from request."}` response into this app's own
`IntegrationError` - proving the request shape, signed-state
verification, and error-handling path are all correct up to Google's
own authentication boundary, the same "hit the real API with
incomplete credentials" verification shape already used for Stripe in
Phase 9.4. A real successful Drive/SharePoint sync against a genuine
OAuth app remains the one thing not verified here, exactly as scoped.

## External tool-call fallback (spec: Phase 6 MCP, Phase 7 generalized to OpenAPI)

`app.agents.resolution.resolve_from_knowledge` is where every path that
has "nothing else to offer" converges: no `INTENT_RESOLVERS` entry for
this intent, and RAG retrieval returned no documents. Before that turns
into a plain "no reliable knowledge found" escalation,
`app.agents.external_tools.propose_external_tool_call` gets one shot at a
different kind of answer - the tenant's connected MCP (Model Context
Protocol) servers **and** OpenAPI/Swagger-described REST APIs, merged
into one catalog for a single LLM selection call rather than trying each
source sequentially:

1. `app.repositories.integrations.IntegrationRepository.list_enabled_by_type("mcp")`
   and `list_enabled_by_type("openapi")` - every enabled integration of
   each type for this tenant (unlike JIRA/SMTP, which assume exactly one
   active connector, a tenant can connect several of either).
2. `app.integrations.mcp_client.list_tools` (Streamable HTTP `tools/list`,
   always live) and `app.integrations.openapi_client.list_operations`
   (reads the spec parsed and cached at "Test" time -
   `Integration.config.spec_cache` - rather than re-fetching a full spec
   on every fallback-triggered message) build one combined `CatalogEntry`
   list. A single integration being unreachable/misconfigured is logged
   and skipped, not fatal.
3. The LLM sees the catalog - each entry's exact argument names and types
   spelled out (`_describe_arguments`, not just a prose description; live
   testing showed the model otherwise guesses plausible-but-wrong key
   names, e.g. `repo_name` instead of a schema's `repoName`) - and returns
   an `ExternalToolSelection` (`app.agents.schemas`) - a *position* in
   that list, or `-1` for "none apply". This is deliberately narrower than
   a general tool-calling loop: the model never invents a tool name, it
   only picks from what's actually connected (rule 17: prefer
   deterministic logic over autonomous LLM decisions - the resolver map
   above it is never overridden, only extended when it has nothing).
4. Before validation, `_substitute_known_placeholders` (spec: Phase 11,
   a real live-testing finding) resolves any redaction placeholder the
   LLM proposed (e.g. `<EMAIL_REDACTED>` - the customer's message was
   already PII-redacted before this LLM call ever saw it, see
   `docs/SECURITY.md`'s PII handling section) into the real value from
   this app's own `Customer` record. Only fields this app actually
   stores are covered (`email` today); anything else is left as the LLM
   proposed it.
5. The chosen (and now placeholder-substituted) arguments are validated
   against that entry's real JSON Schema (`jsonschema.validate` - for
   OpenAPI, this schema was built by `openapi_client.parse_operations`
   resolving the spec's path/query/header parameters and its request
   body's `$ref`s into one flat object schema) before anything is
   proposed - a plausible-looking but schema-invalid call is treated the
   same as "no suitable tool", not silently coerced.

A valid proposal does **not** call anything. It sets
`awaiting_approval=True` and `SupportState.pending_mcp_call` (field name
kept from Phase 6 for checkpoint backward-compatibility; its dict now
carries `source: "mcp"|"openapi"` plus, for `openapi`, the `method`/
`path`/`param_locations` needed to reconstruct the call - the checkpointer
only persists plain JSON-safe state, not the live `OpenApiOperationSpec`
object) exactly the way `resolve_refund` sets `awaiting_approval` for a
refund, so it flows through the same `human_approval_gate` interrupt
described above. The real call - `mcp_client.call_tool` or
`openapi_client.call_operation`, dispatched by `source` - only happens
once a staff member approves the resulting ticket, regardless of source
or HTTP method, never speculatively, because neither an MCP server's nor
an external REST API's actual behavior is reviewed code the way this
codebase's built-in tools are. See `docs/SECURITY.md`'s "External tool
calls" section for the full threat model.

## Storefront-primary commerce routing (spec: Phase 7 A2)

`INTENT_RESOLVERS` (`app.agents.resolution`) answers commerce intents
(`ORDER_STATUS`/`SHIPPING`/`ORDER_CANCEL`/`REFUND`/`RETURNS`/
`PAYMENT_FAILURE`/`SUBSCRIPTION`) from this app's own internal
`orders`/`payments`/`subscriptions` tables by default - fine for a tenant
whose commerce data actually lives there, but for a tenant whose real
storefront is external, those tables are empty and every question
"resolves" as "no orders found." A tenant can instead connect a real
storefront and make it the *primary* path: tag an `mcp`/`openapi`
integration with `config.role: "storefront"`, and
`gather_resolution_facts` routes every commerce intent through it -
before ever reaching `INTENT_RESOLVERS` - via
`app.agents.resolution.resolve_via_storefront`:

1. `_get_storefront_integration(ctx)` looks up the tenant's enabled
   `mcp`/`openapi` integration tagged `role == "storefront"` (first match
   wins - this codebase doesn't route different commerce intents to
   different storefronts).
2. `propose_external_tool_call(ctx, llm, message, role="storefront")` -
   the exact same selection/validation machinery described above in
   "External tool-call fallback," just scoped to only that one
   integration's catalog via the `role` filter on `_discover_catalog`,
   rather than every connected MCP/OpenAPI integration.
3. A mutating proposal (or a read-only one without the opt-in below)
   takes the identical `awaiting_approval`/`pending_mcp_call` path as the
   general fallback - same ticket, same `human_approval_gate` interrupt,
   same execution dispatch on approval. Deliberately **not** run through
   the internal resolvers' customer-pre-confirmation round-trip
   (`customer_already_confirmed`) first - the staff-approval gate alone
   is the safety boundary for a storefront-routed action.
4. **The one auto-execute exception**: if the proposal is a read-only
   (`GET`/`HEAD`) OpenAPI operation *and* that integration has
   `config.auto_execute_reads: true`, `execute_proposal` runs immediately
   - no ticket - and the result becomes a grounded fact in the response.
   MCP proposals are never eligible (no structural read/write signal),
   and a mutating OpenAPI operation never is either, regardless of the
   flag. This is an explicit per-integration admin opt-in, not a default
   - see `docs/SECURITY.md`'s "External tool calls" for the full
   reasoning.

A tenant with no `role: "storefront"` integration is entirely unaffected
- `gather_resolution_facts` falls through to `INTENT_RESOLVERS` exactly
as before this phase existed.

**At most one enabled integration may carry `config.role: "storefront"`
per tenant** (spec: Phase 12 audit). Previously unenforced -
`_get_storefront_integration` did "first match wins" with no defined
ordering across integrations, so which one actually handled a commerce
request was effectively non-deterministic whenever two carried the role
at once. `app.api.routes.integrations._ensure_single_storefront` now
rejects (`ValidationError`, 422) a create/update that would leave a
second enabled `role: "storefront"` integration - staff must disable or
retag the existing one first.

## RAG policy-check gate for commerce actions (spec: Phase 12, generalized Phase 13)

`RETURNS`/`REFUND`/`ORDER_CANCEL` previously proposed or created their
action with no reference to the actual policy documents in the knowledge
base at all - `route_request` sends these intents down the
`action_required` branch, which never runs `knowledge_search_node`, so
`retrieved_documents` was always empty for them. A customer well past a
policy's stated return window got the same treatment as one on day one;
nothing in `app.tools.refunds.create_refund_request` checked this either.
`app.agents.policy_check.check_commerce_policy` closes this gap with one
narrow, bounded structured-output LLM call
(`CommerceEligibilityCheck: qualifies: yes|no|insufficient_data`) - never
open-ended reasoning, matching `app.agents.classifier`'s existing
`generate_structured` pattern:

1. Retrieves the relevant policy document via the tenant-scoped
   `Retriever` (a fixed query per intent - "refund policy - return window
   in days from delivery" for REFUND/RETURNS; ORDER_CANCEL is
   deliberately excluded, see below).
2. Given the policy text plus whatever order status/reference-date is
   actually available, the model answers `yes`/`no`/`insufficient_data`.
   `insufficient_data` (no policy doc found, no order status/date to
   check against, or the policy text doesn't clearly say either way)
   always means "proceed exactly as before this feature existed" - this
   gate can only make a request *stricter* via a clear denial, never
   stricter by blocking on ambiguity.
3. On `deny`, the resolver returns immediately with a policy-grounded
   explanation - the mutating tool call (internal or external) is never
   proposed or executed.

**Wired into exactly two places, deliberately not a third:**
- `resolve_refund` (internal-resolver path for REFUND/RETURNS) - order
  status/estimated-delivery come from the already-fetched order plus one
  extra `get_shipping_status` call (cheap, already an existing tool).
  Runs before the confirmation prompt, so a clearly-denied request never
  even asks the customer to confirm it.
- `resolve_via_storefront`, for REFUND/RETURNS proposals only - order
  status/date come from a second, best-effort read-only lookup
  (`_lookup_order_snapshot_via_storefront`, a second
  `propose_external_tool_call` call scoped to a status-lookup-shaped
  synthetic message, executed only if it selects a non-mutating
  operation) since a storefront's mutating operations typically take
  only an order id, not status/date fields.
- **`ORDER_CANCEL` deliberately has no gate at all**, in either path -
  `app.tools.orders.NON_CANCELLABLE_STATUSES` (internal) and the
  storefront's own status check on its mutating operation (external)
  already enforce the exact rule the seeded Shipping Policy states
  ("cancelled free of charge only while status is 'placed'"),
  deterministically, on every call, with no possibility of being
  bypassed. Adding an LLM-mediated check on top would only add
  latency/cost/a new failure mode for zero additional safety.

`MockLLMProvider` always returns `insufficient_data` for
`CommerceEligibilityCheck` (mirrors `ExternalToolSelection`'s "mock defers
real reasoning" precedent) - every `MOCK_LLM=true` flow is unaffected
unless a test explicitly stubs this schema.

**Generalized (spec: Phase 13)** - `check_commerce_policy` is now a thin
wrapper over a new, reusable `app.agents.policy_check.check_policy_eligibility(
retriever, llm, *, tenant_id, query, question, facts: dict[str, str | None])`,
which any resolver with a real policy document that could plausibly gate
its outcome can call directly - not just the original REFUND/RETURNS/
ORDER_CANCEL commerce-action gate. Two new real call sites, both grounded
in an actual seeded policy document's content (read before deciding to
wire each one in, not assumed):

- **EXCHANGE** (storefront-routed only - no internal resolver exists)
  joined REFUND/RETURNS in `resolve_via_storefront`'s existing gate,
  reusing the return-policy query (no dedicated seeded Exchange Policy
  doc; exchange eligibility conventionally mirrors return windows).
- **Subscription cancellation** (`resolve_subscription`) - the real
  seeded Subscription Policy states annual-plan customers cancelling
  within 14 days of purchase qualify for a prorated refund and should be
  "routed to the refund process instead of a plain cancellation." Nothing
  checked this before Phase 13; every cancellation was treated
  identically regardless of plan/timing. `Subscription` has no `order_id`
  - it is never linked to a refundable `Order` row - so "route to the
  refund process" cannot be automated the way an order refund can; on a
  qualifying `allow`, the resolver escalates for manual handling instead
  of proceeding with a plain cancellation, the honest schema-correct
  outcome rather than a fake automated refund. `SubscriptionResult`
  gained a `started_at` field (from the already-existing
  `Subscription.created_at`, just never exposed) as the "days since
  purchase" fact.

**Audited and deliberately NOT wired into a policy-check gate** (checked
against real code/real seeded policy docs, not assumed - see each
resolver's own docstring for the specific reasoning):
- `resolve_order_cancel`/`resolve_address_change` - the outcome is
  already a deterministic fact from order status
  (`NON_CANCELLABLE_STATUSES`/`NON_ADDRESS_CHANGEABLE_STATUSES`), not a
  policy judgment call.
- `resolve_account_access`'s unlock proposal - the real seeded "Account
  Security Policy" doc governs a *different* scenario (suspected
  fraud/unauthorized access must never be auto-resolved by the AI),
  already handled deterministically and earlier in the pipeline via the
  `SECURITY` intent's `ALWAYS_ESCALATE_INTENTS` membership. A plain
  lockout has no policy eligibility question to gate - `is_locked` is
  already a deterministic fact.
- `_resolve_duplicate_charge`, `resolve_payment_retry`,
  `resolve_profile_update` - each is either a deterministic fact check
  (payment count) or has no seeded policy document addressing it at all.

## Full e-commerce scenario coverage (spec: Phase 13)

Beyond order/fulfillment/payments (already thorough), account-related
coverage was thin - `ACCOUNT_ACCESS`/`PASSWORD_RESET` both routed to one
resolver that only ever sent a verification email, `Customer.is_locked`
was never acted on by anything, and there was no profile/email update, no
account-deletion/GDPR handling, no duplicate-charge dispute, and no
lost-package discrepancy detection. New/changed intents (see
`app.domain.enums.intent`'s six-location-checklist comment for the full
consistency requirement this project has hit before - Phase 9.2's
classifier-drift bug):

- **`PROFILE_UPDATE`** (new intent) - name/email change via
  `app.tools.customer.update_customer_profile` (rejects an email already
  used by another customer in the tenant). The target new value(s) are
  extracted from the customer's RAW message
  (`app.agents.resolution.extract_profile_update_target`, a plain email/
  name regex) *before* `app.security.pii.redact` strips them -
  `resolve_issue` does this explicitly, since a new email is exactly the
  kind of thing PII redaction removes before any resolver ever sees it
  (the same class of problem `_substitute_known_placeholders` already
  fixed once for external-tool arguments - see the "External tool-call
  fallback" section above). Always proposed
  (`awaiting_approval`/`pending_internal_call`), never applied
  immediately.
- **`ACCOUNT_ACCESS`** - split off from sharing `resolve_password_reset`
  with `PASSWORD_RESET`. Now checks `Customer.is_locked`: not locked
  defers to the same password-reset flow as before; locked proposes a
  real `unlock_account` action (also always-approved, never applied
  immediately). A merge-shaped request ("I have two accounts") is
  recognized via a deterministic regex and escalated - no safe automated
  way exists to verify identity across two separate records.
- **`PRIVACY`** - moved into `ALWAYS_ESCALATE_INTENTS`. A real,
  previously-unnoticed bug: `PRIVACY` was in neither
  `app.agents.resolution`'s `KNOWLEDGE_INTENTS` nor `INTENT_RESOLVERS`,
  so `gather_resolution_facts` fell through to its final
  `return ResolutionOutcome()` - every `PRIVACY` message (including a
  GDPR "delete my data" request) silently produced zero facts and no
  escalation. Fixed by adding `PRIVACY` alongside `SECURITY`/`FRAUD`/
  `LEGAL`, which also correctly makes every privacy/data request
  (informational or a deletion request) reach a human, matching this
  app's existing treatment of every other legally-sensitive intent.
- **`BILLING`** gained a real `INTENT_RESOLVERS` entry
  (`resolve_billing`) instead of always falling through to RAG: a
  duplicate/incorrect-charge dispute (real backing data - `Payment` rows;
  proposes a refund of the extra charge via the *existing*
  `create_refund_request` tool, reused not reinvented), a payment-method
  update request (redirected to the secure self-service page - this app
  never accepts card details through chat, full stop), and a gift-card/
  store-credit request (escalated - no backing gift-card system exists
  anywhere in this app or its connected storefront). Everything else
  (invoices, general billing questions, promo codes) falls through to
  the same RAG-grounded `resolve_from_knowledge` behavior BILLING already
  had. **A real, pre-existing routing gap was found and fixed alongside
  this**: `BILLING` was in `route_request`'s `READ_ONLY_DATA_INTENTS`
  (`customer_data` route), which - like `action_required` - never runs
  `knowledge_search_node`, so `state["retrieved_documents"]` was *always*
  empty for a `BILLING` message despite a real seeded "Billing FAQ" doc
  existing; moved to the `knowledge_search` route so `resolve_billing`'s
  RAG fallback actually has something to ground an answer in.
- **`PRODUCT_INFORMATION`** gained a real `INTENT_RESOLVERS` entry
  (`resolve_product_information`): a bulk/wholesale inquiry is
  recognized and escalated with a clear "route to sales" reason (no real
  backing sales system exists) rather than answered from a generic
  product FAQ. Everything else still falls through to RAG, unchanged.
  Real-time stock/availability was investigated and found **not** to be
  exposed by either connected storefront's operation catalog (confirmed
  via each one's actual cached `spec_cache`, not assumed) - deliberately
  left RAG-only, a documented gap rather than a fabricated integration.
- **Lost/never-arrived package** - `resolve_order_status` (shared by
  `ORDER_STATUS`/`SHIPPING`) now detects a real discrepancy: order status
  says `delivered` but the customer's message disputes ever receiving it
  ("shows delivered but I never got it"). Escalates with the discrepancy
  stated plainly - a real lost-package/potential-fraud case, not a
  routine status lookup - rather than just reporting "delivered" as if
  that settles the question.

**Identity-modifying actions never execute during `resolve_issue`.**
`update_customer_profile`/`unlock_account` are `ApprovalLevel.ALWAYS` in
both directions (customer confirmation AND staff approval), and - unlike
`cancel_order` (`ApprovalLevel.SOMETIMES`, which runs immediately and is
only *sometimes* flagged for post-hoc review) - staff approval here must
happen *before* the action takes effect, not after. This needed a new
mechanism: `SupportState.pending_internal_call` (`{"tool": str, "args":
dict}`), set by the resolver instead of calling the tool, propagated
through `resolve_issue` exactly like `pending_mcp_call` already is, and
executed exactly once by a new
`app.workflow.nodes.human_approval._execute_approved_internal_call` -
the internal-tool analogue of `_execute_approved_external_call`,
dispatched via a small `tool name -> (function, args model)` table.
Rejection or an execution failure escalates with a clear reason, exactly
matching the external-tool-call failure path's shape.

**Response tone.** `app.agents.resolution.draft_response`'s prompt
(`RESPONSE_TEMPLATE_RULES`) was rewritten: the prior version's explicit
"structure it around: what I know, what I checked, what I changed..."
instruction reliably produced mechanical, labeled/bulleted output (an LLM
given named categories tends to reproduce them near-verbatim as
headers). Every safety-critical constraint (grounded-only, never claim an
unconfirmed success) is unchanged - only the tone/structure guidance
changed, toward natural prose, no visible section headers, and explicit
anti-corporate-boilerplate wording ("we appreciate your patience", "rest
assured", etc.).

## Expanded commerce scenarios (spec: Phase 8.3)

Four more commerce intents beyond the original seven, each added to
`COMMERCE_INTENTS` (so a connected storefront handles them via
`resolve_via_storefront` "for free" - the LLM tool-selection step is
entirely intent-agnostic) plus, for three of them, an internal
DB-backed resolver for a storefront-less tenant:

- **Partial refunds - no new intent.** `RefundRequest.amount` already
  supported an arbitrary value `<= order.total_amount`;
  `resolve_refund` previously just never passed anything but the full
  total. It now extracts a customer-stated `$`/`dollars`/`usd` amount
  (`_extract_requested_amount`) and, since the confirming "yes" reply on
  turn two carries no amount at all, falls back to scanning the
  customer's own prior turns in `history` for one rather than silently
  reverting to a full refund on confirmation.
- **`SUBSCRIPTION_CHANGE`** (upgrade/downgrade, distinct from
  `SUBSCRIPTION`'s cancel-only handling) - `resolve_subscription_change`
  requires the target plan to be named explicitly (rule 17: no
  inferred/guessed plan), with the same history-fallback pattern as
  partial refunds so the plan name survives the confirm turn.
  `app.tools.subscriptions.update_subscription` gained a `new_plan`
  argument alongside the existing `new_status`.
- **`PAYMENT_RETRY`** - `app.tools.payments.retry_payment` (new; this app
  has no real payment gateway, so a "retry" is a status-only simulation,
  same honesty as `refund_tools` never touching a real processor
  either) flips a `failed` payment to `succeeded`.
- **`ADDRESS_CHANGE`** - deliberately has **no** internal mechanism to
  actually change an address: unlike a plan name or a dollar amount, a
  full mailing address has no single reliable marker to extract from
  free text (rule 17 forbids guessing it). The internal resolver only
  ever does one deterministic thing - report when an order's status
  (`shipped`/`in_transit`/`delivered`) already makes it too late to
  redirect - and otherwise always escalates to a team member. This is
  also a defensible package-redirect-fraud safeguard in its own right,
  not purely a technical limitation. A connected storefront's LLM-driven
  tool selection *can* extract structured address fields from the
  message (the same mechanism `propose_external_tool_call` already uses
  for any other operation's arguments), so this always-escalate behavior
  only actually applies to a storefront-less tenant.
- **`EXCHANGE`** - the one new intent with **no `INTENT_RESOLVERS` entry
  at all**, not even an always-escalate one. This app's `Order` model is
  a flat single-product row with no SKU/variant/line-item concept, so
  there is no way to represent an exchange correctly internally - a
  "cancel the original and note it" pseudo-resolver was considered and
  rejected (it would mislabel `actions_taken` as a cancellation for what
  the customer experiences as a swap, and leave a human to place a
  disconnected replacement order anyway, no better than a plain
  escalation). `EXCHANGE` is in both `COMMERCE_INTENTS` (storefront
  routing) and `resolution.py`'s `KNOWLEDGE_INTENTS` (so a
  storefront-less tenant still gets a real "no reliable knowledge found"
  escalation via `resolve_from_knowledge`, not a silent no-op
  `ResolutionOutcome()`).

**A structural note for future intents**: intent-derived sets are
maintained independently in five places that have already drifted from
each other once - `app.domain.enums.intent` (the `Intent` enum itself,
plus `DATA_REQUIRED_INTENTS`), `app.agents.resolution`
(`COMMERCE_INTENTS`/`KNOWLEDGE_INTENTS`/`INTENT_RESOLVERS`),
`app.workflow.routers.route_request` (its own, separately-populated
`MUTATING_INTENTS`/`READ_ONLY_DATA_INTENTS`/`KNOWLEDGE_INTENTS`),
`app.agents.confirmation` (`CONFIRMATION_CAPABLE_INTENTS`), and
`app.llm.providers.mock` (`_KEYWORD_INTENTS` - without an entry here,
`MOCK_LLM=true`, this project's own zero-setup default *and* its test
suite's mode, never classifies the new intent at all). Adding a new
intent means touching all of these consistently, not just
`resolution.py`. `Intent`'s own `KNOWLEDGE_REQUIRED_INTENTS` is confirmed
dead code (zero references anywhere in `app/`) - do not add to it.

## Inbound storefront webhooks (spec: Phase 8.4)

Every other integration in this codebase is outbound-only - this app is
always the caller (JIRA/WooCommerce/MCP/OpenAPI/email). `app.api.routes.webhooks`
is the one exception: `POST /api/v1/webhooks/storefront/{integration_id}`
lets a connected storefront push events (order shipped/refunded/etc.)
into this app instead of waiting for the customer to ask.

**Auth is fundamentally different here** - there's no staff JWT, since
the caller is an external system, not a person. `app.security.webhooks.verify_webhook_signature`
(spec: Phase 10.1, replacing the original `verify_signature`) checks an
`X-Webhook-Signature` header of the form
`t=<unix timestamp>,v1=<hex HMAC-SHA256 of "{timestamp}.{payload}">`
against `Integration.config.webhook_secret` - the same free-JSON
`config` pattern already used for `role`/`auto_execute_reads`/`spec_cache`,
no schema change needed. **This is a breaking change to the header
contract**: the original Phase 8.4 scheme signed the raw payload only,
with no replay protection at all; Phase 10.1 adopts Stripe's own wire
format (see "Payment gateway (Stripe)" above) instead of inventing a
second bespoke one, sharing its 300-second tolerance window and
multi-`v1=`-value secret-rotation support via a common
`_parse_timestamped_signature` helper in the same module. This is a
hard cutover, not a dual-format fallback - the only real caller of this
route is the committed `demo_storefront/fire_webhook.py`, updated
alongside this change; a real external storefront integrator would need
to adopt the new format too. `verify_signature` (the original scheme)
stays defined and tested as a record of what Phase 8.4 shipped, but no
route calls it anymore. Rotating `config.webhook_secret` itself no
longer requires an admin to hand-type a value into `PUT .../{id}` -
`POST /admin/integrations/{id}/rotate-webhook-secret` (spec: Phase
10.1) generates a fresh `secrets.token_hex(32)` value and returns it
exactly once; every other integration response (including this one's
own subsequent `GET`s) masks a truthy `config.webhook_secret` down to
the boolean `true`, the same "reveal presence, not value" treatment
`credential_keys` already gives encrypted credentials - closing a real,
previously-shipped bug where `config.webhook_secret` (used by both
`stripe` and any storefront-webhook-carrying integration) came back in
plaintext on every integration response.

The integration lookup is deliberately cross-tenant (`session.get(Integration,
integration_id)`, not a `TenantScopedRepository` query) since the
caller has no tenant concept at all, only the `integration_id` it was
configured with - a missing integration, a disabled one, and a bad
signature all return the exact same 401, never a distinguishable 404
(mirrors `app.workflow.runner.resume_workflow`'s "don't reveal whether
the id exists in another tenant" posture, applied here to "don't reveal
whether it exists at all").

**Deliberately not a resume mechanism.** `resume_workflow`'s
`Command(resume=...)` only ever accepts a bool approval against one
specific, already-paused `thread_id` - there is no clean seam to inject
an arbitrary new event into a paused or already-*finished* LangGraph
run, and building one is out of scope here. Instead, a webhook event is
handled entirely outside the graph:

1. **Best-effort correlation** - `app.agents.resolution.resolve_via_storefront`
   already writes the order id it operated on into
   `Conversation.metadata_json["last_order_id"]` (via
   `_extract_order_id_from_arguments`, a heuristic scan for any
   string-valued proposal argument whose key mentions "order" - there's
   no fixed argument name across arbitrary connected storefronts). The
   webhook handler scans the tenant's most recently updated
   conversations (bounded, `_CORRELATION_SCAN_LIMIT = 200`) for a
   matching `last_order_id`, entirely in Python rather than a
   dialect-specific JSON query (Postgres `->>` vs SQLite `json_extract`,
   neither used anywhere else in this codebase) - simpler and portable
   for a best-effort feature at this app's scale.
2. **On a match**: a new, low-priority (`LOW`) `SupportTicket` is created
   on that conversation, `intent="WEBHOOK"` (a literal string, not an
   `Intent` enum value - this ticket is created directly by the webhook
   handler, never passes through `classify_intent`/`route_request`, so
   none of the six intent-set locations above apply to it; falls into
   the general staff queue by default since it's absent from
   `SECURITY_QUEUE_INTENTS`).
3. **On a miss**: `SupportTicket`/`Conversation` both require a real
   `customer_id` (`NOT NULL` FK) that an uncorrelated event has no way to
   supply - rather than inventing a placeholder customer/conversation
   just to force-fit a ticket, the event is logged
   (`storefront_webhook_uncorrelated`) and acknowledged with `200
   {"received": true, "correlated": false}`, not silently dropped, but
   also not surfaced as a ticket with no real owner.

**Real-time push to an active conversation (spec: Phase 10.3)**, closing
the gap this section used to describe as out of scope: on a correlation
hit, alongside creating the `SupportTicket` above, the handler also
calls `app.realtime.connections.get_connection_manager().broadcast(conversation.id,
{"event", "order_id", "ticket_id"})` - a best-effort UX nudge to any
browser tab currently connected to
`GET /api/v1/support/ws/conversations/{conversation_id}` (see
`app.api.routes.support.conversation_socket`) for that exact
conversation. The ticket remains the durable, staff-visible record
regardless of whether anyone was connected to receive the push - this
is additive UX, never a replacement path. `ConnectionManager` is an
in-process `dict[conversation_id, set[WebSocket]]`, correct for a single
API instance and not for a fleet, exactly like this app's
`InMemoryRateLimiter`/`InMemoryVectorStore`/default `AsyncSqliteSaver` -
a real multi-instance deployment needs a pub/sub-backed variant (this
codebase already has Redis via `USE_REDIS`, a natural fit) - not built
in this pass, see `docs/DEPLOYMENT.md`. A browser `WebSocket` can't set
a custom `Authorization` header, so the customer's JWT travels as a
`?token=` query parameter on the WS URL instead, decoded directly via
`decode_access_token` (bypassing the `Header`-based `get_current_customer`
dependency every HTTP route in this file uses) - the same
conversation-ownership check (`conversation.customer_id == customer_id`)
`GET /conversations/{id}` already performs gates the connection. This is
customer-side only, per the original scoping request - no staff-side
(ticket queue) push was built in this pass.

`demo_storefront/fire_webhook.py` (spec: Phase 8.1) is a manual demo/test
script that signs and sends a real event at a real running instance of
this app - see `docs/DEPLOYMENT.md`'s "Manual webhook demo."

**A second real-time push source, extending the same mechanism**: a
staff approval/rejection decision on a paused ticket
(`app.workflow.runner.resume_workflow`) also broadcasts a best-effort
nudge (`{"event": "ticket_decision", "workflow_run_id", "approved"}`)
to the same customer conversation, through the exact same
`ConnectionManager` singleton. This is the case the original push design
didn't cover: the customer isn't the one who triggered the completion (a
staff member did, elsewhere), so without this the only way to find out a
refund was approved is the chat UI's own 5-second `awaiting_approval`
poll. The frontend needs no new handling for this - `useConversationSocket`'s
`onmessage` already invalidates the messages/conversation queries on
*any* message regardless of its shape, so the existing REST refetch
picks up both the new assistant message `send_response` persists during
the resumed graph run and the conversation's updated status. Live-verified
against the real running Docker stack: a real websocket connection
(inside the container - Docker Desktop's Windows port-forwarding still
doesn't support the WS upgrade handshake, the same limitation noted for
the original push) received the exact `ticket_decision` payload the
instant a real `POST /tickets/{id}/approve` call resolved.

## Payment gateway (Stripe) (spec: Phase 9.4)

Before this phase, `app.tools.refunds.create_refund_request`/
`app.tools.payments.retry_payment` never made any real external call -
purely DB-status simulations, and (a separate, real bug fixed in the
same phase - see below) approving a refund ticket never even updated
the `RefundRequest` row itself, only the ticket's own status. A
`stripe`-type `Integration` (`config.webhook_secret` required) makes
both paths real when configured, while leaving today's simulation
exactly as-is for any tenant without one:

- **Refund approval** (`app.workflow.nodes.human_approval`'s refund
  branch, via `_update_refund_status_after_decision` then
  `_issue_stripe_refund`): once a refund's own status is set to
  `"approved"`, if an enabled `stripe` integration exists *and* the
  order's most recent `Payment` carries a `gateway_payment_intent_id`,
  `app.integrations.stripe.StripeClient.create_refund` is actually
  called. Its response is provisional (Stripe confirms real refunds
  asynchronously) - success here only records `gateway`/`gateway_reference`
  on the `RefundRequest`, it does **not** advance `status` to
  `"completed"` itself; only the Stripe webhook (below), once Stripe
  confirms it, does that. A failed gateway call escalates
  (`requires_human=True`) with a clear reason - the refund was approved
  in this app's own records, but actually issuing it failed, which the
  customer's own honest response reflects.
- **Payment retry** (`app.tools.payments.retry_payment`): the same
  configured/`gateway_payment_intent_id`-present condition switches from
  flipping a `Payment`'s status directly to calling
  `StripeClient.confirm_payment_intent` and mapping its real returned
  status back.
- **Stripe webhook** (`POST /api/v1/webhooks/stripe/{integration_id}`,
  `app.api.routes.webhooks`): `payment_intent.succeeded`/
  `payment_intent.payment_failed` update the matching `Payment` (found
  via the new `PaymentRepository.get_by_gateway_payment_intent_id`);
  `refund.updated` (not `charge.refunded` - a Charge object's `refunds`
  is a list, not a single id/status pair the way a Refund object is,
  making `refund.updated` the more directly usable event for this)
  marks the matching `RefundRequest` `"completed"` once Stripe reports
  `status: "succeeded"` (found via the new
  `RefundRepository.get_by_gateway_reference`). Authenticated by
  `app.security.webhooks.verify_stripe_signature` - Stripe's own
  `Stripe-Signature: t=<timestamp>,v1=<hmac>` scheme, genuinely
  different from the plain-hex scheme the storefront webhook (Phase 8.4)
  uses, including a 300-second replay-tolerance window the storefront
  webhook doesn't have (a documented gap there, closed here).
- Stripe's REST API is form-encoded (`data=...`), not JSON - the one
  client in this codebase that deviates from every other integration's
  `json=...` convention (JIRA/WooCommerce/MCP/OpenAPI/Confluence/Notion
  all send JSON). Its secret key doubles as a bearer token
  (`Authorization: Bearer sk_...`), fitting this codebase's existing
  `auth_type: "bearer"` with no new auth code.

**The refund-status bug fix** (independent of Stripe, lands first):
`RefundRepository` had `create`/`get_by_idempotency_key`/`get_for_order`
but no `update_status` - unlike every other commerce repository, which
all have one - and nothing in `human_approval_gate`'s refund branch ever
called one. **Every refund ever approved or rejected through this
system, for its entire history until this fix, left `RefundRequest.status`
permanently `"pending"`** regardless of the decision; only the ticket's
own (correctly-updated) status ever reflected reality. Fixed by finding
the refund via `state["tool_results"]`'s `create_refund_request` entry
(already carries the real `refund_id` - `app.agents.resolution.resolve_refund`
puts it there) and calling the new `RefundRepository.update_status`.

**Explicit cannot-live-verify boundary**: built and tested exclusively
against respx-mocked HTTP shaped to match Stripe's real, public API
documentation, plus one live round trip against the real
`api.stripe.com` using a deliberately fake key (confirming the real
auth-header construction and error-parsing path up to Stripe's own
401 boundary) - no real Stripe account or test-mode keys exist yet to
verify a real refund/webhook end to end. To do that once real test keys
exist: create a `stripe` integration with a real `sk_test_...` key,
configure the webhook endpoint in the Stripe dashboard pointing at this
route, and exercise one real refund through the ticket-approval UI.

## Multi-tenancy (spec §43)

Every domain table mixes in `app.db.base.TenantScopedMixin` (a `tenant_id`
column, default `"default"` - the zero-setup single-tenant path needs no
configuration). `app.repositories.base.TenantScopedRepository` is the base
every repository extends: it takes `tenant_id` in its constructor and
`self._scope(stmt, Model)` appends `.where(Model.tenant_id == self.tenant_id)`
to every query, so a repository instance can only ever see its own
tenant's rows - there is no code path that queries across tenants.

`tenant_id` flows the same way `customer_id`/`conversation_id` already do:

- Both customer and staff JWTs carry a `tenant_id` claim
  (`app.security.auth.create_access_token`/`create_staff_token`, defaulting
  to `DEFAULT_TENANT_ID`). `get_current_customer`/`require_staff_role`
  return it alongside the id/role.
- API routes pass it into `run_workflow`/`resume_workflow`, which put it in
  `SupportState["tenant_id"]` - every workflow node and tool constructs its
  repositories with `state["tenant_id"]`/`ctx.tenant_id`.
- `resume_workflow` additionally checks the staff caller's `tenant_id`
  against the `WorkflowRun`'s before resuming - a staff member from tenant
  A can never approve/reject a ticket belonging to tenant B, and the error
  is identical to "ticket not found" (no cross-tenant existence leak).
- **Vector retrieval isolation**: `app.rag.ingest.knowledge_namespace(tenant_id)`
  namespaces the vector store per tenant (`f"knowledge:{tenant_id}"`); two
  tenants' knowledge bases can never cross-match even with the identical
  query, since `VectorRepository.search` only ever searches one namespace.

## RBAC (spec §36)

`app.domain.enums.role.StaffRole` = `SUPPORT_AGENT | SUPPORT_MANAGER |
ADMIN | SECURITY_AGENT`. `CUSTOMER` is implicit in a customer-scoped JWT
(`scope: "customer"`), not a staff account; `SYSTEM` is a separate token
type (`create_system_token`/`decode_system_token`) for service-to-service
calls (scripts, scheduled jobs) that is never issued to a person.

Tickets are split into two approval queues
(`app.config.policies.roles_allowed_to_approve`):

- **Security queue** (`intent` in `SECURITY`/`FRAUD`/`LEGAL`, spec §52):
  only `SECURITY_AGENT`/`ADMIN` may view or act on these tickets.
- **General queue** (everything else): `SUPPORT_AGENT`/`SUPPORT_MANAGER`/`ADMIN`.

`app.api.routes.tickets._require_role_for_ticket` enforces this *after*
fetching the ticket (the required role set depends on its intent, so it
can't be a static route-level `Depends`) - a `SUPPORT_AGENT` token gets a
403 on a `SECURITY` ticket even though it passed the initial
"is this any authenticated staff member" gate. `POST /api/v1/staff/users`
(ADMIN-only) creates accounts with any role, so RBAC is exercisable beyond
the seed script's four sample accounts (one per role).

## Cost tracking (spec §42)

Every LLM call's token usage flows to a `model_requests` row without any
of the 9 `deps.llm_router.get_model(purpose)` call sites in
`app/workflow/nodes/*.py` needing to know about it:

```
app.llm.providers._langchain_base.LangChainChatProvider
  reads response.usage_metadata (LangChain's standard field)
        v
  computes cost via app.llm.pricing.estimate_cost_usd(model, ...)
        v
  invokes the optional `usage_callback` param on generate()/generate_structured()
        v
app.workflow.graph._traced()  (the same wrapper that already logs workflow_events)
  wraps deps.llm_router in a RecordingLLMRouter for the duration of one
  LLM-calling node, whose callback writes a ModelRequestRepository row
  (tenant/workflow_run_id/node_name/purpose/provider/model/tokens/cost)
  and commits it immediately - the trail survives even if a later node fails
```

`MockLLMProvider` reports zero-cost usage too, so the whole pipeline (not
just the real providers) is exercised in tests with no API key.
`LLM_BUDGET_USD_PER_RUN` (unset = unlimited) is checked in `_traced()`
before running any LLM-calling node: once a run's recorded spend meets the
budget, remaining LLM-calling nodes are skipped (returning
`requires_human=True` instead of calling the model) rather than silently
producing a possibly-truncated answer (spec §42: "stop unnecessary calls
... or escalate").

## Data model

See `migrations/versions/0001_initial_schema.py` for the full schema
(customers, orders/payments/subscriptions/refund_requests, conversations,
messages, workflow_runs, workflow_events, support_tickets,
tool_executions, knowledge_documents, knowledge_chunks, feedback,
audit_logs, idempotency_keys), `0002_vector_embeddings.py` for the
pgvector-backend storage table, `0003_staff_users.py` for staff accounts,
`0004_multi_tenancy.py` for the `tenant_id` columns above, and
`0005_model_requests.py` for cost tracking. `app/domain/models/` holds the
SQLAlchemy ORM models 1:1 with these tables.

## Reliability

- **Retries** (`app.observability.retry`): exponential backoff, gated by
  each `SupportWorkflowError.retryable` flag - auth/validation/policy
  errors are never retried (spec §19).
- **Idempotency** (`app.services.idempotency`, plus a unique
  `idempotency_key` column directly on `refund_requests`): a repeated
  refund request with the same `{conversation_id}:{action}:{request_id}`
  key returns the original result instead of creating a second refund
  (spec §20).
- **Errors** (`app.domain.exceptions`): a `SupportWorkflowError` taxonomy
  with a stable `code`, `retryable`, and `severity`, mapped to HTTP status
  codes in `app.main`'s exception handler and logged with full context.
