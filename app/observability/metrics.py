"""Prometheus metrics (spec §22): technical, AI, and business metrics."""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# --- Technical metrics ---
REQUEST_COUNT = Counter("request_count", "Total support API requests", ["endpoint", "status"])
WORKFLOW_LATENCY = Histogram("workflow_latency_seconds", "End-to-end workflow latency")
LLM_LATENCY = Histogram("llm_latency_seconds", "LLM call latency", ["operation"])
RETRIEVAL_LATENCY = Histogram("retrieval_latency_seconds", "RAG retrieval latency")
EMBEDDING_LATENCY = Histogram("embedding_latency_seconds", "Query-embedding latency within retrieval")
KEYWORD_SEARCH_LATENCY = Histogram("keyword_search_latency_seconds", "RAG keyword-search stage latency")
VECTOR_SEARCH_LATENCY = Histogram("vector_search_latency_seconds", "RAG vector-search stage latency")
RERANK_LATENCY = Histogram("rerank_latency_seconds", "RAG fusion+rerank stage latency")
TOOL_LATENCY = Histogram("tool_latency_seconds", "Tool execution latency", ["tool_name"])
ERROR_COUNT = Counter("error_count", "Errors raised", ["code"])
RETRY_COUNT = Counter("retry_count", "Retry attempts", ["operation"])
TIMEOUT_COUNT = Counter("timeout_count", "Timeouts", ["operation"])

# --- AI metrics ---
INTENT_CLASSIFICATIONS = Counter(
    "intent_classifications_total", "Intent classifications", ["intent"]
)
RETRIEVAL_HITS = Counter("retrieval_hits_total", "Retrieval calls above/below threshold", ["hit"])
RESPONSE_GROUNDEDNESS = Histogram("response_groundedness_score", "Groundedness score per response")
RESPONSE_CONFIDENCE = Histogram("response_confidence_score", "Response confidence score")
ESCALATIONS = Counter("escalations_total", "Escalations", ["reason"])
TOOL_SUCCESS = Counter("tool_calls_total", "Tool call outcomes", ["tool_name", "outcome"])

# --- Business metrics ---
FIRST_CONTACT_RESOLUTIONS = Counter("first_contact_resolutions_total", "Resolved on first pass")
RESOLUTION_TIME = Histogram("resolution_time_seconds", "Time to resolution")
REPEAT_CONTACTS = Counter("repeat_contacts_total", "Repeat contacts for same conversation")
