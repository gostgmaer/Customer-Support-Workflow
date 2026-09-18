from app.security.pii import redact, redact_dict, strip_sensitive_fields


def test_redact_email():
    assert redact("Contact me at john@example.com please") == "Contact me at <EMAIL_REDACTED> please"


def test_redact_phone():
    result = redact("Call me at 415-555-0132")
    assert "<PHONE_REDACTED>" in result


def test_redact_dict_nested():
    data = {"note": "email me at a@b.com", "nested": {"phone": "415-555-0100"}}
    redacted = redact_dict(data)
    assert redacted["note"] == "email me at <EMAIL_REDACTED>"
    assert "<PHONE_REDACTED>" in redacted["nested"]["phone"]


def test_strip_sensitive_fields():
    data = {"password": "secret", "password_hash": "x", "email": "a@b.com"}
    stripped = strip_sensitive_fields(data)
    assert "password" not in stripped
    assert "password_hash" not in stripped
    assert stripped["email"] == "a@b.com"


def test_redact_valid_card_number():
    # 4111 1111 1111 1111 is a well-known Luhn-valid test card number.
    result = redact("My card is 4111 1111 1111 1111, please charge it")
    assert result == "My card is <CARD_REDACTED>, please charge it"


def test_non_luhn_digit_run_is_not_mislabeled_as_a_card():
    # 16 digits but not Luhn-valid - e.g. an internal order/tracking id.
    # It may still be redacted as a precaution (a bare long digit run also
    # matches the phone-number pattern), but must never be labeled CARD -
    # that would misrepresent it as a validated payment card number.
    result = redact("Order reference 1234567890123456 confirmed")
    assert "<CARD_REDACTED>" not in result


def test_luhn_valid_digits_without_separators_are_still_caught():
    result = redact("Card number 4111111111111111 on file")
    assert "<CARD_REDACTED>" in result


def test_redact_ip_address():
    result = redact("Request came from 192.168.1.100 during the incident")
    assert result == "Request came from <IP_REDACTED> during the incident"
