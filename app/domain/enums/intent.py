from enum import StrEnum


class Intent(StrEnum):
    ACCOUNT_ACCESS = "ACCOUNT_ACCESS"
    PASSWORD_RESET = "PASSWORD_RESET"
    ORDER_STATUS = "ORDER_STATUS"
    ORDER_CANCEL = "ORDER_CANCEL"
    REFUND = "REFUND"
    PAYMENT_FAILURE = "PAYMENT_FAILURE"
    BILLING = "BILLING"
    SUBSCRIPTION = "SUBSCRIPTION"
    SHIPPING = "SHIPPING"
    RETURNS = "RETURNS"
    # spec: Phase 8.3 - additional commerce scenarios beyond the original
    # seven. EXCHANGE deliberately has no internal DB-backed resolver
    # (see app.agents.resolution's COMMERCE_INTENTS comment) - it only
    # ever resolves via a connected storefront.
    SUBSCRIPTION_CHANGE = "SUBSCRIPTION_CHANGE"
    ADDRESS_CHANGE = "ADDRESS_CHANGE"
    PAYMENT_RETRY = "PAYMENT_RETRY"
    EXCHANGE = "EXCHANGE"
    PRODUCT_INFORMATION = "PRODUCT_INFORMATION"
    TECHNICAL_SUPPORT = "TECHNICAL_SUPPORT"
    BUG_REPORT = "BUG_REPORT"
    COMPLAINT = "COMPLAINT"
    FEATURE_REQUEST = "FEATURE_REQUEST"
    SECURITY = "SECURITY"
    FRAUD = "FRAUD"
    LEGAL = "LEGAL"
    PRIVACY = "PRIVACY"
    UNKNOWN = "UNKNOWN"


# Intents that always require deterministic escalation regardless of confidence.
ALWAYS_ESCALATE_INTENTS = {
    Intent.SECURITY,
    Intent.FRAUD,
    Intent.LEGAL,
}

# Intents that require calling customer-data tools to answer accurately.
DATA_REQUIRED_INTENTS = {
    Intent.ACCOUNT_ACCESS,
    Intent.ORDER_STATUS,
    Intent.ORDER_CANCEL,
    Intent.REFUND,
    Intent.PAYMENT_FAILURE,
    Intent.BILLING,
    Intent.SUBSCRIPTION,
    Intent.SHIPPING,
    Intent.RETURNS,
    Intent.SUBSCRIPTION_CHANGE,
    Intent.ADDRESS_CHANGE,
    Intent.PAYMENT_RETRY,
    Intent.EXCHANGE,
}

# Intents best answered from the knowledge base.
KNOWLEDGE_REQUIRED_INTENTS = {
    Intent.PRODUCT_INFORMATION,
    Intent.TECHNICAL_SUPPORT,
    Intent.BILLING,
    Intent.RETURNS,
    Intent.SUBSCRIPTION,
    Intent.SHIPPING,
}
