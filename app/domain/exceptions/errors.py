"""Structured application errors (spec §21).

Every error carries a stable `code` (for logs/metrics/client responses),
a `retryable` flag (drives the retry policy in app.observability.retry),
and a `severity` (drives alerting/escalation).
"""

from __future__ import annotations


class SupportWorkflowError(Exception):
    code: str = "UNKNOWN_ERROR"
    retryable: bool = False
    severity: str = "medium"

    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "severity": self.severity,
            "details": self.details,
        }


class ValidationError(SupportWorkflowError):
    code = "VALIDATION_ERROR"
    retryable = False
    severity = "low"


class AuthenticationError(SupportWorkflowError):
    code = "AUTHENTICATION_ERROR"
    retryable = False
    severity = "high"


class AuthorizationError(SupportWorkflowError):
    code = "AUTHORIZATION_ERROR"
    retryable = False
    severity = "high"


class ToolError(SupportWorkflowError):
    code = "TOOL_ERROR"
    retryable = True
    severity = "medium"


class LLMError(SupportWorkflowError):
    code = "LLM_ERROR"
    retryable = True
    severity = "medium"


class RetrievalError(SupportWorkflowError):
    code = "RETRIEVAL_ERROR"
    retryable = True
    severity = "medium"


class PolicyError(SupportWorkflowError):
    code = "POLICY_ERROR"
    retryable = False
    severity = "high"


class TimeoutError_(SupportWorkflowError):
    code = "TIMEOUT_ERROR"
    retryable = True
    severity = "medium"


class RateLimitError(SupportWorkflowError):
    code = "RATE_LIMIT_ERROR"
    retryable = True
    severity = "low"


class IntegrationError(SupportWorkflowError):
    """An external system (JIRA/WooCommerce/SMTP/custom) call failed or is
    misconfigured - see app.integrations. Never allowed to break the core
    workflow: automatic hooks (app.integrations.hooks) always catch this
    and log rather than raise."""

    code = "INTEGRATION_ERROR"
    retryable = True
    severity = "medium"
