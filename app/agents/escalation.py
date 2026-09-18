"""Escalation manager (spec §17): builds a self-contained ticket so a human
agent never has to reread the entire conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class EscalationTicket:
    conversation_id: str
    customer_id: str
    workflow_run_id: str
    intent: str
    priority: str
    summary: str
    customer_problem: str
    actions_taken: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    relevant_documents: list[str] = field(default_factory=list)
    reason_for_escalation: str = ""
    recommended_next_action: str = ""


def build_escalation_ticket(
    *,
    conversation_id: str,
    customer_id: str,
    workflow_run_id: str,
    intent: str,
    priority: str,
    latest_message: str,
    facts: list[str],
    tool_calls: list[dict],
    retrieved_documents: list[str],
    escalation_reason: str,
) -> EscalationTicket:
    recommended = {
        "SECURITY": "Verify identity, review account access logs, and confirm no unauthorized changes.",
        "FRAUD": "Freeze affected payment method(s) pending investigation.",
        "LEGAL": "Route to legal/compliance team before any customer-facing response.",
    }.get(intent, "Review the conversation and verified facts, then respond to the customer directly.")

    return EscalationTicket(
        conversation_id=conversation_id,
        customer_id=customer_id,
        workflow_run_id=workflow_run_id,
        intent=intent,
        priority=priority,
        summary="; ".join(facts) if facts else "No verified facts were gathered before escalation.",
        customer_problem=latest_message,
        actions_taken=[c["tool"] for c in tool_calls],
        tools_used=list({c["tool"] for c in tool_calls}),
        relevant_documents=retrieved_documents,
        reason_for_escalation=escalation_reason,
        recommended_next_action=recommended,
    )
