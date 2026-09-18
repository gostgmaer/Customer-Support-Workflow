"""Uploads the evaluation datasets in tests/evaluation/dataset.py to
LangSmith (spec §15: intent/retrieval/tool-selection/safety datasets).

Run with:  python scripts/evaluation/upload_langsmith_datasets.py

Requires LANGSMITH_TRACING=true and LANGSMITH_API_KEY to be set - without
them this prints a clear message and exits 0 (safe to wire into CI
unconditionally; it simply no-ops when LangSmith isn't configured, same
policy as the rest of this app's optional integrations).

Idempotent: re-running updates each dataset's examples rather than
duplicating them, via `Client.create_examples(dangerously_allow_filesystem=False)`
after clearing prior examples for that dataset name - see `_replace_dataset`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.config import get_settings  # noqa: E402
from app.observability.logging import get_logger  # noqa: E402
from tests.evaluation.dataset import (  # noqa: E402
    EVAL_CASES,
    RETRIEVAL_CASES,
    SAFETY_CASES,
    TOOL_SELECTION_CASES,
)

logger = get_logger(__name__)


def _replace_dataset(client, name: str, description: str, examples: list[dict]) -> None:  # noqa: ANN001
    from langsmith.utils import LangSmithNotFoundError

    try:
        dataset = client.read_dataset(dataset_name=name)
        for example in client.list_examples(dataset_id=dataset.id):
            client.delete_example(example.id)
    except LangSmithNotFoundError:
        dataset = client.create_dataset(dataset_name=name, description=description)

    client.create_examples(dataset_id=dataset.id, examples=examples)
    print(f"  {name}: {len(examples)} examples")


def main() -> int:
    settings = get_settings()
    if not (settings.langsmith_tracing and settings.langsmith_api_key):
        print("LangSmith not configured (LANGSMITH_TRACING/LANGSMITH_API_KEY unset) - skipping.")
        return 0

    from langsmith import Client

    client = Client(api_key=settings.langsmith_api_key)

    print("Uploading evaluation datasets to LangSmith...")

    _replace_dataset(
        client,
        "customer-support-intent-classification",
        "spec §35/§15: message -> expected intent/priority-floor/escalation",
        [
            {
                "inputs": {"message": c.message},
                "outputs": {
                    "intent": c.expected_intent,
                    "priority_at_least": c.expected_priority_at_least,
                    "requires_human": c.expected_requires_human,
                },
            }
            for c in EVAL_CASES
        ],
    )

    _replace_dataset(
        client,
        "customer-support-retrieval",
        "spec §15: question -> expected knowledge-base document category",
        [
            {"inputs": {"question": c.question}, "outputs": {"expected_category": c.expected_category}}
            for c in RETRIEVAL_CASES
        ],
    )

    _replace_dataset(
        client,
        "customer-support-tool-selection",
        "spec §15: message -> expected first tool call",
        [
            {
                "inputs": {"message": c.message, "intent": c.intent},
                "outputs": {"expected_tool": c.expected_tool},
            }
            for c in TOOL_SELECTION_CASES
        ],
    )

    _replace_dataset(
        client,
        "customer-support-safety",
        "spec §15: attack -> expected refusal/escalation, never compliance",
        [
            {
                "inputs": {"attack_message": c.attack_message},
                "outputs": {"expected_requires_human": c.expected_requires_human, "note": c.note},
            }
            for c in SAFETY_CASES
        ],
    )

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
