from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union
from guardrail.config import PIICustomPattern, PIIConfig
from guardrail.sanitizer.patterns import PATTERNS, PATTERN_PRECEDENCE, luhn_verify


class AnonymizationSession:
    """Request-scoped session tracking masked entities and reversible mappings."""

    def __init__(self, reversible: bool = True) -> None:
        self.reversible = reversible
        self.mask_to_original: Dict[str, str] = {}
        self.original_to_mask: Dict[str, str] = {}
        self.counters: Dict[str, int] = {}
        self.detection_counts: Dict[str, int] = {}

    def get_or_create_mask(self, category: str, original_val: str, custom_placeholder: Optional[str] = None) -> str:
        if original_val in self.original_to_mask:
            return self.original_to_mask[original_val]

        self.counters[category] = self.counters.get(category, 0) + 1
        idx = self.counters[category]

        if custom_placeholder:
            # e.g., "[CUSTOM_{idx}]" or "[MY_MASK]"
            if "{idx}" in custom_placeholder or "{n}" in custom_placeholder:
                mask = custom_placeholder.replace("{idx}", str(idx)).replace("{n}", str(idx))
            else:
                mask = f"[{custom_placeholder.strip('[]')}_{idx}]"
        else:
            mask = f"[{category.upper()}_{idx}]"

        self.original_to_mask[original_val] = mask
        if self.reversible:
            self.mask_to_original[mask] = original_val

        self.detection_counts[category] = self.detection_counts.get(category, 0) + 1
        return mask

    def deanonymize(self, text: str) -> str:
        """Restores original values from placeholder tokens if reversible."""
        if not self.reversible or not self.mask_to_original:
            return text

        result = text
        # Replace in reverse order of mask length to prevent prefix collisions
        for mask, original in sorted(self.mask_to_original.items(), key=lambda x: len(x[0]), reverse=True):
            result = result.replace(mask, original)
        return result


class PIISanitizer:
    """High-speed PII scanning and redaction engine."""

    def __init__(self, config: Optional[PIIConfig] = None) -> None:
        self.config = config or PIIConfig()
        self.compiled_rules: List[Tuple[str, re.Pattern[str], Optional[str]]] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        if not self.config.enabled:
            return

        # 1. User custom patterns take precedence
        for name, rule in self.config.custom_patterns.items():
            if isinstance(rule, str):
                pat = re.compile(rule)
                self.compiled_rules.append((name, pat, None))
            elif isinstance(rule, PIICustomPattern):
                pat = re.compile(rule.pattern)
                self.compiled_rules.append((name, pat, rule.placeholder))

        # 2. Built-in patterns compiled according to precedence order
        for pattern_name in PATTERN_PRECEDENCE:
            if pattern_name in self.config.patterns and pattern_name in PATTERNS:
                self.compiled_rules.append((pattern_name, PATTERNS[pattern_name], None))

    def create_session(self) -> AnonymizationSession:
        return AnonymizationSession(reversible=self.config.reversible)

    def sanitize_text(self, text: str, session: AnonymizationSession) -> str:
        """Sanitizes sensitive entities in a single text string."""
        if not self.config.enabled or not text:
            return text

        sanitized = text
        for category, regex, custom_placeholder in self.compiled_rules:
            def replace_match(match: re.Match[str]) -> str:
                matched_text = match.group(0)
                # Additional check for credit card Luhn if category is credit_card
                if category == "credit_card":
                    digits_only = re.sub(r"\D", "", matched_text)
                    if len(digits_only) < 13 or not luhn_verify(digits_only):
                        return matched_text
                return session.get_or_create_mask(category, matched_text, custom_placeholder)

            sanitized = regex.sub(replace_match, sanitized)

        return sanitized

    def sanitize_messages(self, messages: List[Dict[str, Any]], session: AnonymizationSession) -> List[Dict[str, Any]]:
        """Sanitizes an OpenAI-style list of messages."""
        if not self.config.enabled:
            return messages

        sanitized_messages: List[Dict[str, Any]] = []
        for msg in messages:
            msg_copy = dict(msg)
            content = msg_copy.get("content")
            if isinstance(content, str):
                msg_copy["content"] = self.sanitize_text(content, session)
            elif isinstance(content, list):
                # Multimodal content parts
                new_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text" and "text" in part:
                        p_copy = dict(part)
                        p_copy["text"] = self.sanitize_text(p_copy["text"], session)
                        new_parts.append(p_copy)
                    else:
                        new_parts.append(part)
                msg_copy["content"] = new_parts
            sanitized_messages.append(msg_copy)
        return sanitized_messages

    def sanitize_prompt(self, prompt: Union[str, List[str]], session: AnonymizationSession) -> Union[str, List[str]]:
        """Sanitizes legacy completion prompt string or list."""
        if not self.config.enabled:
            return prompt
        if isinstance(prompt, str):
            return self.sanitize_text(prompt, session)
        if isinstance(prompt, list):
            return [self.sanitize_text(p, session) for p in prompt]
        return prompt


class StreamingPIISanitizer:
    """Sliding-window buffer for sanitizing PII in Server-Sent Events (SSE) streams.
    Prevents entities like email addresses from slipping through when split across chunk boundaries.
    """

    def __init__(self, sanitizer: PIISanitizer, session: AnonymizationSession, buffer_size: int = 64) -> None:
        self.sanitizer = sanitizer
        self.session = session
        self.buffer_size = buffer_size
        self._buffer: str = ""

    def process_chunk(self, chunk_text: str) -> str:
        """Processes an incoming text fragment and yields sanitized safe prefix."""
        self._buffer += chunk_text
        if len(self._buffer) <= self.buffer_size:
            return ""

        # Find the last whitespace delimiter before cutoff to prevent cutting across words/tokens
        cutoff = len(self._buffer) - self.buffer_size
        delimiter_idx = -1
        for i in range(cutoff, -1, -1):
            if self._buffer[i] in " \t\n\r":
                delimiter_idx = i + 1
                break

        if delimiter_idx <= 0:
            # If buffer grows very large without whitespace, cut anyway
            if len(self._buffer) > self.buffer_size * 4:
                delimiter_idx = cutoff
            else:
                return ""

        to_process = self._buffer[:delimiter_idx]
        self._buffer = self._buffer[delimiter_idx:]

        return self.sanitizer.sanitize_text(to_process, self.session)

    def flush(self) -> str:
        """Flushes remaining buffered text when stream concludes."""
        remaining = self._buffer
        self._buffer = ""
        return self.sanitizer.sanitize_text(remaining, self.session)
