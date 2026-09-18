from enum import StrEnum


class Channel(StrEnum):
    WEB = "web"
    EMAIL = "email"
    MESSAGING = "messaging"
    DASHBOARD = "dashboard"
    API = "api"
