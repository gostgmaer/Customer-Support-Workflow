"""PII detection/redaction (spec §25).

Applied to anything customer-supplied or tool-returned before it is logged
or placed into customer_context / prompts, so the LLM and logs only ever
see what they need.

Card-like digit runs are validated with a Luhn checksum before being
redacted as `<CARD_REDACTED>` (rather than redacting every 13-19 digit
sequence unconditionally) - a plain digit-count regex would also catch
order/tracking numbers and other harmless internal identifiers, which
would make the redaction noisy enough that a human reviewer starts
ignoring it.
"""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\-.\s()]{8,}\d")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_TOKEN_RE = re.compile(r"\b(?:sk|pk|ghp|xox[baprs])-?[A-Za-z0-9_-]{16,}\b")
_CARD_CANDIDATE_RE = re.compile(r"\b\d(?:[ -]?\d){12,18}\b")


def _luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _redact_cards(text: str) -> str:
    def _replace(match: re.Match) -> str:
        digits = re.sub(r"[ -]", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            return "<CARD_REDACTED>"
        return match.group(0)

    return _CARD_CANDIDATE_RE.sub(_replace, text)


# Cards are redacted first (Luhn-validated, see _redact_cards) so a genuine
# card number is labeled CARD rather than being swallowed by the broader
# PHONE pattern - both patterns would otherwise happily match "4111 1111
# 1111 1111". EMAIL/SSN/IP/TOKEN/PHONE then run on what's left.
_SIMPLE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", _EMAIL_RE),
    ("SSN", _SSN_RE),
    ("IP", _IPV4_RE),
    ("TOKEN", _TOKEN_RE),
    ("PHONE", _PHONE_RE),
]


def redact(text: str) -> str:
    """Replace detected PII with `<TYPE_REDACTED>` placeholders."""
    redacted = _redact_cards(text)
    for label, pattern in _SIMPLE_PATTERNS:
        redacted = pattern.sub(f"<{label}_REDACTED>", redacted)
    return redacted


def redact_dict(data: dict) -> dict:
    """Recursively redact string values in a dict (used before logging tool results)."""
    result: dict = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = redact(value)
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = [redact(v) if isinstance(v, str) else v for v in value]
        else:
            result[key] = value
    return result


SENSITIVE_FIELD_NAMES = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "card_number",
    "cvv",
    "ssn",
    "secret",
}


def strip_sensitive_fields(data: dict) -> dict:
    """Drop fields that must never leave the persistence layer at all
    (as opposed to being redacted-in-place)."""
    return {k: v for k, v in data.items() if k.lower() not in SENSITIVE_FIELD_NAMES}
