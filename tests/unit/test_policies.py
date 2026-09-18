from app.config.policies import ApprovalLevel, get_tool_policy


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
