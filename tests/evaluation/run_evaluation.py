"""Evaluation harness (spec §35, §40).

Run with:  python tests/evaluation/run_evaluation.py

Computes intent accuracy, priority-floor pass rate, and escalation
accuracy against the labeled dataset in dataset.py using whichever
provider is configured (mock by default, MOCK_LLM=false to use the real
router). Exits non-zero if intent
accuracy or escalation accuracy drop below the configured minimums, so CI
(see .github/workflows/ci.yml) fails the build on a regression per the
spec's "any prompt/model change must pass the evaluation suite" rule.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.agents.classifier import classify_intent, classify_priority  # noqa: E402
from app.domain.enums.priority import PRIORITY_ORDER, Priority  # noqa: E402
from app.llm.router import get_llm_router  # noqa: E402
from tests.evaluation.dataset import EVAL_CASES  # noqa: E402

MIN_INTENT_ACCURACY = 0.80
MIN_ESCALATION_ACCURACY = 0.95


async def main() -> int:
    router = get_llm_router()
    llm = router.get_model("intent_classification")

    intent_correct = 0
    priority_ok = 0
    escalation_correct = 0

    for case in EVAL_CASES:
        intent_result = await classify_intent(llm, case.message)
        priority_result = await classify_priority(llm, case.message, intent=intent_result.intent)

        intent_match = intent_result.intent == case.expected_intent
        intent_correct += int(intent_match)

        actual_rank = PRIORITY_ORDER.get(Priority(priority_result.priority), 0)
        expected_rank = PRIORITY_ORDER.get(Priority(case.expected_priority_at_least), 0)
        priority_ok += int(actual_rank >= expected_rank)

        escalation_match = intent_result.requires_human == case.expected_requires_human
        escalation_correct += int(escalation_match)

        status = "OK" if intent_match and escalation_match else "MISMATCH"
        print(
            f"[{status}] '{case.message[:50]}' -> intent={intent_result.intent} "
            f"(expected {case.expected_intent}), priority={priority_result.priority}, "
            f"requires_human={intent_result.requires_human} (expected {case.expected_requires_human})"
        )

    n = len(EVAL_CASES)
    intent_accuracy = intent_correct / n
    priority_pass_rate = priority_ok / n
    escalation_accuracy = escalation_correct / n

    print("\n--- Evaluation summary ---")
    print(f"intent_accuracy:       {intent_accuracy:.2%} ({intent_correct}/{n})")
    print(f"priority_floor_pass:   {priority_pass_rate:.2%} ({priority_ok}/{n})")
    print(f"escalation_accuracy:   {escalation_accuracy:.2%} ({escalation_correct}/{n})")

    if intent_accuracy < MIN_INTENT_ACCURACY or escalation_accuracy < MIN_ESCALATION_ACCURACY:
        print("\nEvaluation FAILED minimum thresholds.")
        return 1

    print("\nEvaluation PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
