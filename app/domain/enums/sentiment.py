from enum import StrEnum


class Sentiment(StrEnum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    FRUSTRATED = "FRUSTRATED"
    ANGRY = "ANGRY"
    URGENT = "URGENT"
    DISTRESSED = "DISTRESSED"


# Sentiment that should nudge priority up a notch but never gate approval/denial on its own.
ESCALATION_SIGNAL_SENTIMENTS = {
    Sentiment.ANGRY,
    Sentiment.URGENT,
    Sentiment.DISTRESSED,
}
