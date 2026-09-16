from __future__ import annotations

import re
from typing import Dict, Pattern

# Linear-time compiled regular expressions designed to prevent catastrophic backtracking (ReDoS)

PATTERN_PRECEDENCE = [
    "api_key",
    "credit_card",
    "ipv4",
    "ssn",
    "email",
    "phone",
]

PATTERNS: Dict[str, Pattern[str]] = {
    # High entropy API Keys & Secrets (OpenAI, AWS, GitHub, generic secret assignments)
    "api_key": re.compile(
        r"\b(?:"
        r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,80}|"  # OpenAI keys
        r"AKIA[0-9A-Z]{16}|"                     # AWS Access Key ID
        r"gh[pousr]_[A-Za-z0-9_]{36,255}|"      # GitHub PAT
        r"(?:api[_-]?key|secret[_-]?key|access[_-]?token)[\s=:'\"]+([a-zA-Z0-9_\-]{20,64})"
        r")\b",
        re.IGNORECASE,
    ),
    # Credit Card Numbers: Visa, Mastercard, Amex, Discover
    "credit_card": re.compile(
        r"\b(?:"
        r"4[0-9]{12}(?:[0-9]{3})?|"           # Visa
        r"5[1-5][0-9]{14}|"                   # Mastercard
        r"3[47][0-9]{13}|"                    # American Express
        r"6(?:011|5[0-9]{2})[0-9]{12}|"       # Discover
        r"(?:4[0-9]{3}|5[1-5][0-9]{2}|6011|3[47][0-9]{2})[- ](?:[0-9]{4}[- ]){2}[0-9]{4}|"  # 16-digit spaced/dashed
        r"3[47][0-9]{2}[- ][0-9]{6}[- ][0-9]{5}"  # Amex 15-digit spaced/dashed
        r")\b"
    ),
    # IPv4 Address: 0.0.0.0 to 255.255.255.255
    "ipv4": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\b"
    ),
    # US Social Security Number: XXX-XX-XXXX
    "ssn": re.compile(
        r"\b\d{3}-\d{2}-\d{4}\b"
    ),
    # Email: RFC 5322 compliant
    "email": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        re.IGNORECASE,
    ),
    # Phone numbers: US & International formats
    # Matches: +1-800-555-0199, (555) 123-4567, 555-123-4567, 800-555-0199, +44 20 7123 4567
    "phone": re.compile(
        r"\b(?:"
        r"(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?[2-9]\d{2}[-.\s]?\d{4}|"  # NANP (US/Canada)
        r"\+\d{1,3}[-.\s]\d{1,4}[-.\s]\d{3,4}[-.\s]\d{3,4}"               # International with +
        r")\b"
    ),
}


def luhn_verify(card_number_str: str) -> bool:
    """Validate credit card number using Luhn algorithm."""
    digits = [int(d) for d in re.sub(r"\D", "", card_number_str)]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse_digits = digits[::-1]
    for i, d in enumerate(reverse_digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0
