from __future__ import annotations

import collections
import threading
import time
from typing import Any, Deque, Dict, Optional, Tuple
from guardrail.config import BudgetConfig


class ClientBudgetState:
    """Tracks sliding window request and token timestamps for a single client."""

    def __init__(self) -> None:
        # Deque of (timestamp, token_count)
        self.entries: Deque[Tuple[float, int]] = collections.deque()
        self.total_tokens_lifetime: int = 0
        self.total_requests_lifetime: int = 0

    def prune(self, cutoff_time: float) -> None:
        """Removes entries older than cutoff_time."""
        while self.entries and self.entries[0][0] < cutoff_time:
            self.entries.popleft()

    @property
    def current_tokens(self) -> int:
        return sum(tokens for _, tokens in self.entries)

    @property
    def current_requests(self) -> int:
        return len(self.entries)


class BudgetExceededError(Exception):
    def __init__(self, message: str, status_code: int = 429, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": {
                "message": str(self),
                "type": "rate_limit_error" if self.status_code == 429 else "budget_exhausted_error",
                "code": "token_budget_exceeded" if self.status_code == 429 else "insufficient_quota",
                "details": self.details,
            }
        }


class TokenBudgetLimiter:
    """Sliding-window token budget and rate limiter."""

    def __init__(self, config: Optional[BudgetConfig] = None) -> None:
        self.config = config or BudgetConfig()
        self._clients: Dict[str, ClientBudgetState] = {}
        self._lock = threading.Lock()

    def _get_client_state(self, client_id: str) -> ClientBudgetState:
        if client_id not in self._clients:
            self._clients[client_id] = ClientBudgetState()
        return self._clients[client_id]

    def check_and_reserve(
        self,
        client_id: str,
        estimated_tokens: int,
    ) -> None:
        """Checks if a request within estimated tokens can proceed under sliding window budget.

        Raises:
            BudgetExceededError if limit is reached.
        """
        if not self.config.enabled:
            return

        now = time.time()
        cutoff = now - self.config.sliding_window_seconds

        with self._lock:
            # 1. Check per-request token limit
            if (
                self.config.max_tokens_per_request > 0
                and estimated_tokens > self.config.max_tokens_per_request
            ):
                raise BudgetExceededError(
                    f"Estimated prompt tokens ({estimated_tokens}) exceeds max allowed per request ({self.config.max_tokens_per_request}).",
                    status_code=400,
                    details={
                        "estimated_tokens": estimated_tokens,
                        "max_tokens_per_request": self.config.max_tokens_per_request,
                    },
                )

            state = self._get_client_state(client_id)
            state.prune(cutoff)

            # 2. Check requests per window limit
            if (
                self.config.max_requests_per_minute > 0
                and state.current_requests >= self.config.max_requests_per_minute
            ):
                status = self.config.reject_status_code
                raise BudgetExceededError(
                    f"Request rate limit exceeded. Max {self.config.max_requests_per_minute} requests per {self.config.sliding_window_seconds}s.",
                    status_code=status,
                    details={
                        "current_requests": state.current_requests,
                        "limit": self.config.max_requests_per_minute,
                        "window_seconds": self.config.sliding_window_seconds,
                    },
                )

            # 3. Check tokens per window limit
            projected_tokens = state.current_tokens + estimated_tokens
            if (
                self.config.max_tokens_per_minute > 0
                and projected_tokens > self.config.max_tokens_per_minute
            ):
                status = self.config.reject_status_code
                raise BudgetExceededError(
                    f"Token rate limit exceeded. Projected {projected_tokens} tokens exceeds limit of {self.config.max_tokens_per_minute} per {self.config.sliding_window_seconds}s.",
                    status_code=status,
                    details={
                        "current_tokens": state.current_tokens,
                        "estimated_tokens": estimated_tokens,
                        "limit": self.config.max_tokens_per_minute,
                        "window_seconds": self.config.sliding_window_seconds,
                    },
                )

    def record_usage(self, client_id: str, actual_tokens: int) -> None:
        """Records actual tokens consumed after response delivery."""
        if not self.config.enabled:
            return

        now = time.time()
        cutoff = now - self.config.sliding_window_seconds

        with self._lock:
            state = self._get_client_state(client_id)
            state.prune(cutoff)
            state.entries.append((now, actual_tokens))
            state.total_tokens_lifetime += actual_tokens
            state.total_requests_lifetime += 1

    def get_stats(self, client_id: str) -> Dict[str, Any]:
        """Returns statistics for a specific client."""
        now = time.time()
        cutoff = now - self.config.sliding_window_seconds

        with self._lock:
            state = self._get_client_state(client_id)
            state.prune(cutoff)
            return {
                "client_id": client_id,
                "current_window_requests": state.current_requests,
                "current_window_tokens": state.current_tokens,
                "lifetime_requests": state.total_requests_lifetime,
                "lifetime_tokens": state.total_tokens_lifetime,
                "window_seconds": self.config.sliding_window_seconds,
            }

    def reset(self) -> None:
        """Resets all tracking states (useful for test suites)."""
        with self._lock:
            self._clients.clear()
