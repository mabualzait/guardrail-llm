from __future__ import annotations

import pytest
from guardrail.config import PIICustomPattern, PIIConfig
from guardrail.sanitizer.engine import PIISanitizer, StreamingPIISanitizer


def test_pii_sanitization_builtins():
    config = PIIConfig(enabled=True, reversible=True)
    sanitizer = PIISanitizer(config)
    session = sanitizer.create_session()

    raw_text = (
        "Hello, my email is alice.smith@example.org and my phone is +1-555-867-5309. "
        "My SSN is 123-45-6789 and my server IP is 192.168.1.100. "
        "Don't share my API key sk-proj-abc123def456ghi789jkl0123456789! "
        "Also ping alice.smith@example.org again."
    )

    sanitized = sanitizer.sanitize_text(raw_text, session)

    # Assert entities masked
    assert "alice.smith@example.org" not in sanitized
    assert "+1-555-867-5309" not in sanitized
    assert "123-45-6789" not in sanitized
    assert "192.168.1.100" not in sanitized
    assert "sk-proj-abc123def456ghi789jkl0123456789" not in sanitized

    # Check consistent placeholder assignment for repeated entity
    assert sanitized.count("[EMAIL_1]") == 2
    assert "[PHONE_1]" in sanitized
    assert "[SSN_1]" in sanitized
    assert "[IPV4_1]" in sanitized
    assert "[API_KEY_1]" in sanitized

    # Check reversibility
    restored = session.deanonymize(sanitized)
    assert restored == raw_text


def test_credit_card_luhn():
    config = PIIConfig(enabled=True, reversible=True)
    sanitizer = PIISanitizer(config)
    session = sanitizer.create_session()

    # Valid Luhn Visa test card: 4111 1111 1111 1111
    valid_card = "My card is 4111 1111 1111 1111."
    sanitized_valid = sanitizer.sanitize_text(valid_card, session)
    assert "4111 1111 1111 1111" not in sanitized_valid
    assert "[CREDIT_CARD_1]" in sanitized_valid

    # Invalid Luhn number should NOT be masked
    invalid_card = "Random digits 4111 1111 1111 1112."
    sanitized_invalid = sanitizer.sanitize_text(invalid_card, session)
    assert "4111 1111 1111 1112" in sanitized_invalid


def test_custom_patterns():
    config = PIIConfig(
        enabled=True,
        custom_patterns={
            "ticket": r"\bINC-\d{5}\b",
            "badge": PIICustomPattern(pattern=r"\bBADGE-[A-Z0-9]{4}\b", placeholder="[ID_{idx}]"),
        },
    )
    sanitizer = PIISanitizer(config)
    session = sanitizer.create_session()

    text = "Please check incident INC-98765 for employee with BADGE-AB12."
    sanitized = sanitizer.sanitize_text(text, session)
    assert "INC-98765" not in sanitized
    assert "[TICKET_1]" in sanitized
    assert "BADGE-AB12" not in sanitized
    assert "[ID_1]" in sanitized

    restored = session.deanonymize(sanitized)
    assert restored == text


def test_sanitize_messages():
    sanitizer = PIISanitizer()
    session = sanitizer.create_session()

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Reach me at contact@corp.io"},
                {"type": "image_url", "image_url": {"url": "https://example.com/img.png"}},
            ],
        },
        {"role": "assistant", "content": "Got it, I will write to contact@corp.io."},
    ]

    sanitized = sanitizer.sanitize_messages(messages, session)
    assert sanitized[0]["content"] == "You are a helpful assistant."
    assert sanitized[1]["content"][0]["text"] == "Reach me at [EMAIL_1]"
    assert sanitized[2]["content"] == "Got it, I will write to [EMAIL_1]."

    # Restore in response
    deanonymized_content = session.deanonymize(sanitized[2]["content"])
    assert deanonymized_content == "Got it, I will write to contact@corp.io."


def test_disabled_pii():
    config = PIIConfig(enabled=False)
    sanitizer = PIISanitizer(config)
    session = sanitizer.create_session()

    text = "Email test@example.com"
    assert sanitizer.sanitize_text(text, session) == text


def test_streaming_pii_sanitizer():
    sanitizer = PIISanitizer()
    session = sanitizer.create_session()
    streaming = StreamingPIISanitizer(sanitizer, session, buffer_size=10)

    # Split "test@example.com" across chunks
    part1 = "Please email me at te"
    part2 = "st@example.c"
    part3 = "om right away for support."

    chunk1_out = streaming.process_chunk(part1)
    chunk2_out = streaming.process_chunk(part2)
    chunk3_out = streaming.process_chunk(part3)
    chunk4_out = streaming.flush()

    total_output = chunk1_out + chunk2_out + chunk3_out + chunk4_out

    assert "test@example.com" not in total_output
    assert "[EMAIL_1]" in total_output
    assert "right away for support." in total_output
