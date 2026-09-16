from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

# Attempt tiktoken import if available, else use zero-dependency heuristic
try:
    import tiktoken  # type: ignore

    _TIKTOKEN_ENCODING = tiktoken.get_encoding("cl100k_base")
    HAS_TIKTOKEN = True
except Exception:
    _TIKTOKEN_ENCODING = None
    HAS_TIKTOKEN = False

# Fast word/punctuation regex for zero-dependency tokenizer heuristic (BPE approximation)
_TOKEN_SPLIT_RE = re.compile(r" ?[A-Za-z0-9_]+|[^\w\s]|\n+|\s{2,}", re.UNICODE)


def estimate_tokens_heuristic(text: str) -> int:
    """Fast deterministic token estimator with zero external dependencies.

    Accurately approximates BPE tokenization (~3.8 to 4 chars per token)
    taking word length, punctuation, and whitespace into account.
    """
    if not text:
        return 0

    tokens = 0
    for match in _TOKEN_SPLIT_RE.finditer(text):
        chunk = match.group(0)
        chunk_len = len(chunk)
        if chunk.isspace():
            tokens += max(1, chunk_len // 4)
        elif chunk.lstrip().isalnum():
            alnum_len = len(chunk.lstrip())
            if alnum_len <= 6:
                tokens += 1
            else:
                tokens += 1 + (alnum_len - 6 + 3) // 4
        else:
            tokens += 1

    return max(1, tokens)


def count_tokens(text: str) -> int:
    """Returns exact token count if tiktoken is installed, otherwise high-precision heuristic."""
    if not text:
        return 0
    if HAS_TIKTOKEN and _TIKTOKEN_ENCODING is not None:
        try:
            return len(_TIKTOKEN_ENCODING.encode(text))
        except Exception:
            pass
    return estimate_tokens_heuristic(text)


def count_messages_tokens(messages: List[Dict[str, Any]], model: Optional[str] = None) -> int:
    """Calculates prompt tokens for a list of chat completion messages,
    accounting for message framing overhead (~3 tokens per message + 3 tokens reply primer).
    """
    num_tokens = 3  # every reply is primed with <|start|>assistant<|message|>
    for msg in messages:
        num_tokens += 3  # <|start|>{role/name}\n{content}<|end|>
        for key, val in msg.items():
            if isinstance(val, str):
                num_tokens += count_tokens(val)
            elif isinstance(val, list):
                for part in val:
                    if isinstance(part, dict) and part.get("type") == "text" and "text" in part:
                        num_tokens += count_tokens(part["text"])
    return num_tokens


def count_prompt_tokens(prompt: Union[str, List[str], List[Dict[str, Any]]]) -> int:
    """Unified entrypoint for counting tokens across legacy prompt and chat messages."""
    if isinstance(prompt, str):
        return count_tokens(prompt)
    if isinstance(prompt, list):
        if prompt and isinstance(prompt[0], dict):
            return count_messages_tokens(prompt)
        return sum(count_tokens(p) for p in prompt)
    return 0
