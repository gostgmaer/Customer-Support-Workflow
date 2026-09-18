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
