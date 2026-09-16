from __future__ import annotations

import time
import pytest
from guardrail.budget.limiter import BudgetExceededError, TokenBudgetLimiter
from guardrail.budget.tokenizer import (
    count_messages_tokens,
    count_prompt_tokens,
    count_tokens,
    estimate_tokens_heuristic,
)
from guardrail.config import BudgetConfig


def test_tokenizer_heuristic():
    sample = "Hello world! This is a test of the zero-dependency heuristic tokenizer."
    tokens = count_tokens(sample)
    assert 10 <= tokens <= 20

    # Message overhead
    messages = [
        {"role": "user", "content": "What is the capital of France?"},
        {"role": "assistant", "content": "The capital of France is Paris."},
    ]
    msg_tokens = count_messages_tokens(messages)
    assert msg_tokens > len(messages) * 3

    assert count_prompt_tokens("Just a prompt") > 0
    assert count_prompt_tokens(["Prompt 1", "Prompt 2"]) > 0


def test_budget_limiter_rate_limits():
    config = BudgetConfig(
        enabled=True,
        max_tokens_per_request=100,
        max_requests_per_minute=2,
        max_tokens_per_minute=150,
        sliding_window_seconds=60,
        reject_status_code=429,
    )
    limiter = TokenBudgetLimiter(config)
    client_id = "user_123"

    # Request 1: 50 tokens (allowed)
    limiter.check_and_reserve(client_id, estimated_tokens=50)
    limiter.record_usage(client_id, actual_tokens=50)

    # Request 2: 60 tokens (allowed)
    limiter.check_and_reserve(client_id, estimated_tokens=60)
    limiter.record_usage(client_id, actual_tokens=60)

    # Request 3: Exceeds max_requests_per_minute (limit is 2)
    with pytest.raises(BudgetExceededError) as exc_req:
        limiter.check_and_reserve(client_id, estimated_tokens=10)
    assert exc_req.value.status_code == 429
    assert "Request rate limit exceeded" in str(exc_req.value)

    stats = limiter.get_stats(client_id)
    assert stats["current_window_requests"] == 2
    assert stats["current_window_tokens"] == 110


def test_budget_limiter_token_ceiling_and_payment_required():
    config = BudgetConfig(
        enabled=True,
        max_tokens_per_request=1000,
        max_requests_per_minute=100,
        max_tokens_per_minute=200,
        reject_status_code=402,
    )
    limiter = TokenBudgetLimiter(config)
    client = "tenant_xyz"

    limiter.check_and_reserve(client, 150)
    limiter.record_usage(client, 150)

    # Next request needs 60 tokens, total 210 > 200 limit -> triggers 402
    with pytest.raises(BudgetExceededError) as exc_tok:
        limiter.check_and_reserve(client, 60)
    assert exc_tok.value.status_code == 402
    assert "Token rate limit exceeded" in str(exc_tok.value)


def test_budget_per_request_limit():
    config = BudgetConfig(enabled=True, max_tokens_per_request=50)
    limiter = TokenBudgetLimiter(config)

    with pytest.raises(BudgetExceededError) as exc:
        limiter.check_and_reserve("c1", 60)
    assert exc.value.status_code == 400
    assert "exceeds max allowed per request" in str(exc.value)
