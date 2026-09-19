# Evaluation

`tests/evaluation/run_evaluation.py` (spec §35) scores whichever provider
`app.llm.router` resolves for the `intent_classification` purpose against
the labeled dataset in `tests/evaluation/dataset.py` (mock by default):

```bash
make evaluate
# or against real Gemini: MOCK_LLM=false GOOGLE_API_KEY=... python tests/evaluation/run_evaluation.py
# or against real Grok:   MOCK_LLM=false DEFAULT_LLM_PROVIDER=xai XAI_API_KEY=... python tests/evaluation/run_evaluation.py
```

It reports:

- **intent_accuracy** - exact match against `expected_intent`.
- **priority_floor_pass** - the classified priority is at or above
  `expected_priority_at_least` (a floor, not an exact match, since
  reasonable classifiers may over-escalate priority but should never
  under-escalate).
- **escalation_accuracy** - `requires_human` matches `expected_requires_human`.

The script exits non-zero if `intent_accuracy < 0.80` or
`escalation_accuracy < 0.95`, and CI (`.github/workflows/ci.yml`) fails the
build on that exit code - per spec §35/§40, "any production prompt/model
change must pass the evaluation suite."

## Extending the dataset

Add a case to `EVAL_CASES` in `tests/evaluation/dataset.py` for every real
misclassification you diagnose in production, per spec §35's regression
rule: "create regression tests for every important failure." Keep cases
short and unambiguous - this dataset is a floor, not a substitute for the
full workflow tests in `tests/workflow/`.

**Case study (spec: Phase 9.2)**: three real-LLM misclassifications
(Phase A2, Phase 8.3, Phase 8.4 - each a message with an order-id token
like `ORD-9001` misclassifying as `UNKNOWN`) were each individually
diagnosed via live testing but never turned into a dataset case, despite
this section's own instruction, until the third recurrence prompted
actually root-causing the pattern (`app.agents.classifier`'s prompt
never named the intent taxonomy - see `docs/ARCHITECTURE.md`'s "Intent
classification reliability"). The three cases now in `EVAL_CASES` are
the regression tests that should have existed after the first
incident - if you notice yourself describing a live-testing finding as
"the same issue as before," that's the signal to stop and add the case
instead of cross-referencing it a third time.

## Workflow-level evaluation

`tests/workflow/test_scenarios.py` covers the spec §34 scenarios end-to-end
through the real API (order status, refund confirmation + human approval,
security escalation, out-of-scope/no-hallucination, and the confirmation-
carryover edge case). These exercise routing, tool authorization, the
policy/grounding/review gates, and the interrupt/resume mechanism together
- run them whenever you change `app/workflow/` or `app/agents/`.

## RAG retrieval upgrade evaluation (spec: Phase 11)

The Phase 11 spec explicitly required: "Do not invent results. If
evaluation data is unavailable, explicitly mark the values as NOT
MEASURED." There is no existing labeled retrieval-evaluation dataset in
this codebase (`RETRIEVAL_CASES` below checks *document category*, not
ranking quality against a graded relevance scale) - so no
Recall@K/Precision@K/MRR/NDCG numbers are reported here, before or
after. Fabricating query/expected-chunk pairs to produce plausible-looking
before/after numbers would misrepresent measurement that didn't happen.

| Metric | Status |
|---|---|
| Recall@K | NOT MEASURED |
| Precision@K | NOT MEASURED |
| MRR | NOT MEASURED |
| NDCG | NOT MEASURED |
| Latency (p50/p95/p99) | NOT MEASURED (per-stage histograms exist as of this phase - `EMBEDDING_LATENCY`, `VECTOR_SEARCH_LATENCY`, `KEYWORD_SEARCH_LATENCY`, `RERANK_LATENCY` in `app.observability.metrics` - but no load test has been run to report percentiles) |

**What was actually measured instead**, matching this project's own
established practice of live-verifying against the real running stack
rather than a synthetic benchmark:

- The exact failure mode the spec's own audit reproduced ("How many days
  can I return an item within of purchase?" ranking Shipping Policy
  above Refund Policy, with a blended/unfocused generated answer) was
  re-run against the real running app with real `gemini-embedding-2`
  embeddings and the real pgvector backend, in a clean tenant namespace
  isolated from this dev environment's accumulated test data: Refund
  Policy now ranks first (`0.6741` vs Shipping Policy's `0.6694`).
- Two further real queries ("What is your refund policy for damaged
  items?", "How long does shipping take?") were checked in the same
  session and correctly returned their respective documents first with
  clear score separation, as a basic non-regression spot-check alongside
  the primary reproduction case.
- A real, previously-hidden bug was caught by this same live testing
  (not by a unit test): `rerank()`'s vector-weight constant, calibrated
  for `HashingEmbedder`'s coarse cosine scores, silently let a lexically-
  similar-but-wrong document beat a much stronger real semantic match.
  Fixed via `RERANK_SEMANTIC_VECTOR_WEIGHT` (see `docs/ARCHITECTURE.md`'s
  hybrid retrieval section for the full account) and covered by a
  deterministic regression test (`tests/unit/test_retriever.py`) that
  reproduces the same conflicting-documents shape without needing a real
  API call.
- Real pgvector storage (HNSW-indexed `vector` column) and real hybrid
  keyword search (`tsvector`/GIN) were confirmed working end-to-end
  against the actual Postgres service in `docker-compose.yml` - a real
  ingest, a real `ORDER BY embedding_vec <=> ... LIMIT ...` query, and a
  real `ts_rank`/`plainto_tsquery` query all ran and returned correct,
  expected results.

This is evidence that the specific, demonstrated problem is fixed - not
a claim of overall retrieval-quality improvement at scale, which would
require the labeled dataset this codebase doesn't have.

## What this evaluation harness does *not* cover

Retrieval precision/recall and groundedness scoring against a large,
human-labeled corpus are out of scope for this build's curated dataset
(10 cases). `tests/integration/test_rag_pipeline.py` covers retrieval
correctness (current-vs-expired document filtering, below-threshold
behavior) at the unit/integration level instead. If you need statistically
meaningful retrieval metrics, extend `dataset.py` with a much larger
labeled set and add precision/recall computation to `run_evaluation.py`
following the same pattern.

## LangSmith datasets (spec §15)

`tests/evaluation/dataset.py` also has three smaller labeled sets beyond
`EVAL_CASES`, mirroring spec §15's required dataset categories:
`RETRIEVAL_CASES` (question -> expected knowledge-base document category),
`TOOL_SELECTION_CASES` (message -> the tool
`app.agents.resolution`'s deterministic resolver should call first), and
`SAFETY_CASES` (an attack/injection message -> expected
refusal-or-escalation, never compliance). These aren't scored locally by
`run_evaluation.py` - they exist to be uploaded to LangSmith for
tracing-linked evaluation there instead:

```bash
LANGSMITH_TRACING=true LANGSMITH_API_KEY=... python scripts/evaluation/upload_langsmith_datasets.py
```

The script creates (or idempotently replaces the examples in, if
re-run) four LangSmith datasets:
`customer-support-intent-classification`, `customer-support-retrieval`,
`customer-support-tool-selection`, and `customer-support-safety`. Without
`LANGSMITH_TRACING`/`LANGSMITH_API_KEY` set it prints a message and exits
0 - safe to wire into CI unconditionally alongside `make evaluate`, since
it simply no-ops when LangSmith isn't configured (the same policy as this
app's other optional integrations). This no-op path is what
`tests/unit/test_langsmith_upload_script.py` actually verifies in CI; the
real-upload path needs a live LangSmith project and is documented rather
than covered by an automated test - exercise it manually against a real
`LANGSMITH_API_KEY` before relying on it.
