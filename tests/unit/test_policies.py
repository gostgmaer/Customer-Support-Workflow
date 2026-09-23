from datetime import UTC, datetime

from app.config.policies import (
    SLA_FIRST_RESPONSE_MINUTES,
    SLA_RESOLUTION_MINUTES,
    ApprovalLevel,
    compute_sla_due_at,
    get_tool_policy,
)


def test_read_only_tool_has_no_approval_requirements():
    policy = get_tool_policy("get_order")
    assert policy.ai_allowed
    assert policy.customer_confirmation == ApprovalLevel.NONE
    assert policy.human_approval == ApprovalLevel.NONE


def test_refund_requires_confirmation_and_approval():
    policy = get_tool_policy("create_refund_request")
    assert policy.customer_confirmation == ApprovalLevel.ALWAYS
    assert policy.human_approval == ApprovalLevel.ALWAYS


def test_unknown_tool_fails_closed():
    policy = get_tool_policy("delete_everything")
    assert policy.ai_allowed is False
    assert policy.human_approval == ApprovalLevel.ALWAYS


def test_security_investigation_never_ai_allowed():
    policy = get_tool_policy("security_investigation")
    assert policy.ai_allowed is False


def test_compute_sla_due_at_uses_priority_specific_targets():
    created = datetime(2026, 1, 1, tzinfo=UTC)
    first_response, resolution = compute_sla_due_at("CRITICAL", created)
    assert (first_response - created).total_seconds() / 60 == SLA_FIRST_RESPONSE_MINUTES["CRITICAL"]
    assert (resolution - created).total_seconds() / 60 == SLA_RESOLUTION_MINUTES["CRITICAL"]


def test_compute_sla_due_at_orders_targets_by_priority_severity():
    created = datetime(2026, 1, 1, tzinfo=UTC)
    _, critical_resolution = compute_sla_due_at("CRITICAL", created)
    _, low_resolution = compute_sla_due_at("LOW", created)
    assert critical_resolution < low_resolution


def test_compute_sla_due_at_unknown_priority_falls_back_to_low():
    created = datetime(2026, 1, 1, tzinfo=UTC)
    unknown_first, unknown_resolution = compute_sla_due_at("NOT_A_REAL_PRIORITY", created)
    low_first, low_resolution = compute_sla_due_at("LOW", created)
    assert unknown_first == low_first
    assert unknown_resolution == low_resolution
