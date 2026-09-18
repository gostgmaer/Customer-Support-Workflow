from enum import StrEnum


class StaffRole(StrEnum):
    """Spec §36 RBAC roles. CUSTOMER isn't listed here - it's implicit in a
    customer-scoped JWT (`scope: "customer"`, see app.security.auth), not a
    staff account. SYSTEM is a separate token type (`create_system_token`)
    for service-to-service calls, not a staff role either."""

    SUPPORT_AGENT = "SUPPORT_AGENT"
    SUPPORT_MANAGER = "SUPPORT_MANAGER"
    ADMIN = "ADMIN"
    SECURITY_AGENT = "SECURITY_AGENT"


ALL_STAFF_ROLES = tuple(r.value for r in StaffRole)
