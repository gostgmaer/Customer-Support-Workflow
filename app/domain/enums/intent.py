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
    # spec: Phase 13 - profile/contact info changes (name, email). Distinct
    # from ACCOUNT_ACCESS/PASSWORD_RESET (getting back INTO the account) and
    # from BILLING/payment-method concerns - this is "change what's on the
    # account", always human-approved (see app.config.policies).
    PROFILE_UPDATE = "PROFILE_UPDATE"
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
# spec: Phase 13 audit - PRIVACY was NOT here despite SECURITY/FRAUD/LEGAL
# being here, and app.agents.resolution had no KNOWLEDGE_INTENTS/
# INTENT_RESOLVERS entry for it either - a PRIVACY-classified message
# (including a GDPR "delete my data" request) silently produced an empty
# ResolutionOutcome() with zero facts and no escalation. A privacy/data
# request (informational or a deletion request) is exactly the kind of
# thing that should always reach a human, matching this app's existing
# treatment of every other legally-sensitive intent - fixed here rather
# than only handling the deletion sub-case, since the bug affected every
# PRIVACY message, not just deletion requests.
ALWAYS_ESCALATE_INTENTS = {
    Intent.SECURITY,
    Intent.FRAUD,
    Intent.LEGAL,
    Intent.PRIVACY,
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
    Intent.PROFILE_UPDATE,
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
