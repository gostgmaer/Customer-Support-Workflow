"""Grounding validation (§15) + policy guard (§16).

Grounding is checked deterministically first (no verified facts => never
grounded, regardless of what the LLM says) and only then handed to the LLM
for a claim-by-claim check - this way a provider hallucinating "looks fine"
cannot override the hard rule that an empty fact set can never ground a
response.
"""

from __future__ import annotations

from app.agents.schemas import GroundingCheck, PolicyCheck
from app.llm.base import LLMProvider
from app.security.prompt_security import build_prompt_messages

_GROUNDING_RULES = (
    "Check whether every factual claim in the RESPONSE is supported by one of "
    "the VERIFIED FACTS. List any claim that is not supported as an "
    "ungrounded_claim. If there are no verified facts, the response cannot be "
    "grounded unless it explicitly asks a clarifying question or explains it "
    "cannot help."
)

_POLICY_RULES = (
    "Check the RESPONSE for: unsupported promises, unauthorized actions, "
    "privacy violations, sensitive data exposure, refund-policy violations, "
    "security/legal issues, incorrect escalation handling, or claims about "
    "tool results that were not actually returned. Set approved=false and "
    "list violations if any are found."
)


async def check_grounding(llm: LLMProvider, *, response: str, facts: list[str]) -> GroundingCheck:
    if not facts:
        return GroundingCheck(
            grounded=False, ungrounded_claims=["no verified facts available"], confidence=0.0
        )

    facts_text = "\n".join(f"- {f}" for f in facts)
    messages = build_prompt_messages(
        business_policies="",
        developer_rules=f"{_GROUNDING_RULES}\n\nVERIFIED FACTS:\n{facts_text}\n\nRESPONSE:\n{response}",
        retrieved_knowledge=[],
        customer_message=response,
    )
    return await llm.generate_structured(messages, schema=GroundingCheck)


async def check_policy(
    llm: LLMProvider, *, response: str, intent: str, tool_results: list[dict]
) -> PolicyCheck:
    context = f"Intent: {intent}\nTool results: {tool_results}\nRESPONSE:\n{response}"
    messages = build_prompt_messages(
        business_policies="", developer_rules=f"{_POLICY_RULES}\n\n{context}",
        retrieved_knowledge=[], customer_message=response,
    )
    return await llm.generate_structured(messages, schema=PolicyCheck)
