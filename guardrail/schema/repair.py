from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Tuple


def extract_json_block(text: str) -> str:
    """Extracts raw JSON content from Markdown code blocks or conversational text."""
    if not text:
        return ""

    # Check for markdown code fences (e.g. ```json ... ``` or ``` ... ```)
    fence_pattern = re.compile(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", re.IGNORECASE)
    matches = fence_pattern.findall(text)
    if matches:
        # Return the first match trimmed
        return matches[0].strip()

    # If no fences, find the span between the first { or [ and the last } or ]
    start_brace = text.find("{")
    start_bracket = text.find("[")

    if start_brace == -1 and start_bracket == -1:
        return text.strip()

    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        start = start_brace
        end = text.rfind("}")
    else:
        start = start_bracket
        end = text.rfind("]")

    if start != -1 and end != -1 and end > start:
        return text[start : end + 1].strip()

    if start != -1:
        return text[start:].strip()

    return text.strip()


def strip_comments(text: str) -> str:
    """Removes single-line // and multi-line /* */ comments outside of quoted strings."""
    result = []
    in_string = False
    escape = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        # Check for single-line comment
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            # Skip until newline
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        # Check for multi-line comment
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2  # skip */
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def fix_trailing_commas(text: str) -> str:
    """Removes trailing commas right before closing braces or brackets outside strings."""
    result = []
    in_string = False
    escape = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        if ch == ",":
            # Look ahead past whitespace for closing } or ]
            j = i + 1
            while j < n and text[j].isspace():
                j += 1
            if j < n and text[j] in "}]":
                # Skip the trailing comma
                i += 1
                continue

        result.append(ch)
        i += 1

    return "".join(result)


def fix_single_quotes(text: str) -> str:
    """Converts Python-style single quotes to double quotes for keys and values."""
    # Quick check if single quotes exist
    if "'" not in text:
        return text

    result = []
    in_double = False
    in_single = False
    escape = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if in_double:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_double = False
            i += 1
            continue

        if in_single:
            if escape:
                result.append(ch)
                escape = False
            elif ch == "\\":
                escape = True
                result.append(ch)
            elif ch == "'":
                in_single = False
                result.append('"')
            else:
                if ch == '"':
                    result.append('\\"')
                else:
                    result.append(ch)
            i += 1
            continue

        if ch == '"':
            in_double = True
            result.append(ch)
            i += 1
            continue

        if ch == "'":
            in_single = True
            result.append('"')
            i += 1
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def fix_python_literals(text: str) -> str:
    """Replaces True, False, None with valid JSON lowercase literals outside strings."""
    # Pattern to match unquoted True, False, None
    pattern = re.compile(r'\b(True|False|None)\b')

    # Quick search
    if not re.search(pattern, text):
        return text

    replacements = {"True": "true", "False": "false", "None": "null"}

    result = []
    in_string = False
    escape = False
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]
        if in_string:
            result.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue

        # Look for literal keywords
        matched = False
        for lit, rep in replacements.items():
            k = len(lit)
            if text[i : i + k] == lit:
                # Check word boundaries
                prev_char = text[i - 1] if i > 0 else " "
                next_char = text[i + k] if i + k < n else " "
                if not (prev_char.isalnum() or prev_char == "_") and not (next_char.isalnum() or next_char == "_"):
                    result.append(rep)
                    i += k
                    matched = True
                    break
        if not matched:
            result.append(ch)
            i += 1

    return "".join(result)


def close_unclosed_structures(text: str) -> str:
    """Closes unclosed double-quotes, curly braces, and square brackets in correct order."""
    stack: List[str] = []
    in_string = False
    escape = False

    for ch in text:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()

    repaired = text.rstrip()
    if in_string:
        repaired += '"'

    # Remove any trailing comma at the end before closing braces
    repaired = repaired.rstrip()
    if repaired.endswith(","):
        repaired = repaired[:-1].rstrip()

    while stack:
        repaired += stack.pop()

    return repaired


def repair_json(text: str) -> str:
    """Applies all deterministic repair heuristics to broken JSON string."""
    cleaned = extract_json_block(text)
    cleaned = strip_comments(cleaned)
    cleaned = fix_python_literals(cleaned)
    cleaned = fix_single_quotes(cleaned)
    cleaned = fix_trailing_commas(cleaned)
    cleaned = close_unclosed_structures(cleaned)
    cleaned = fix_trailing_commas(cleaned)
    return cleaned


def parse_or_repair_json(text: str) -> Tuple[Any, bool]:
    """Attempts fast native parse. If invalid, applies deterministic repairs and re-parses.

    Returns:
        Tuple of (parsed_data, was_repaired).
    Raises:
        json.JSONDecodeError if parsing fails even after repair attempts.
    """
    if not text or not text.strip():
        raise ValueError("Empty or whitespace-only JSON input")

    # 1. Fast path: Direct json.loads
    try:
        return json.loads(text.strip()), False
    except Exception:
        pass

    # 2. Extract markdown block or braces first
    extracted = extract_json_block(text)
    try:
        return json.loads(extracted), True
    except Exception:
        pass

    # 3. Full deterministic repair pass
    repaired = repair_json(text)
    return json.loads(repaired), True
